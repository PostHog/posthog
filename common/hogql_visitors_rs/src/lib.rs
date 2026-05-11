//! Rust-backed feature extractor for the HogQL AST.
//!
//! Two strategies exposed for comparison:
//!
//! * `extract_features_py(query)` — walks Python AST objects in place via
//!   PyO3, using `intern!`'d attribute names and cached AST class type
//!   pointers (dispatch is `is_exact_instance(&type)`, not class-name
//!   string compare).
//!
//! * `extract_features_via_mirror(query)` — converts the Python AST to a
//!   Rust-native enum mirror once, then walks the mirror natively. For
//!   single-visitor use the conversion dominates; the win is amortising
//!   the conversion across multiple visitors over the same query (via
//!   `to_mirror` + `extract_features_from_mirror`).

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::{PyList, PyTuple, PyType};
use std::collections::BTreeSet;

const INTERESTING_EVENTS: &[&str] = &[
    "$ai_generation",
    "$ai_span",
    "$ai_trace",
    "$ai_embedding",
    "$ai_metric",
    "$ai_feedback",
    "$exception",
    "$web_vitals",
    "$feature_flag_called",
];

fn is_interesting_event(name: &str) -> bool {
    INTERESTING_EVENTS.contains(&name)
}

// -----------------------------------------------------------------------------
// Cached AST class type pointers, populated on first use.
// -----------------------------------------------------------------------------
//
// Both strategies use `is_exact_instance(&cached_type)` for dispatch instead
// of pulling the class name out of `node.get_type().name()` and comparing
// strings. Pointer compare wins, especially since the AST class set is small
// and known at module load time.

struct AstTypes {
    select_query: Py<PyType>,
    select_set_query: Py<PyType>,
    join_expr: Py<PyType>,
    compare_operation: Py<PyType>,
    and_: Py<PyType>,
    or_: Py<PyType>,
    not_: Py<PyType>,
    alias: Py<PyType>,
    field: Py<PyType>,
    constant: Py<PyType>,
    tuple_: Py<PyType>,
    array: Py<PyType>,
}

static AST_TYPES: GILOnceCell<AstTypes> = GILOnceCell::new();

fn ast_types(py: Python<'_>) -> PyResult<&AstTypes> {
    AST_TYPES.get_or_try_init(py, || {
        let m = py.import_bound("posthog.hogql.ast")?;
        let fetch = |name: &str| -> PyResult<Py<PyType>> {
            Ok(m.getattr(name)?.downcast::<PyType>()?.clone().unbind())
        };
        Ok(AstTypes {
            select_query: fetch("SelectQuery")?,
            select_set_query: fetch("SelectSetQuery")?,
            join_expr: fetch("JoinExpr")?,
            compare_operation: fetch("CompareOperation")?,
            and_: fetch("And")?,
            or_: fetch("Or")?,
            not_: fetch("Not")?,
            alias: fetch("Alias")?,
            field: fetch("Field")?,
            constant: fetch("Constant")?,
            tuple_: fetch("Tuple")?,
            array: fetch("Array")?,
        })
    })
}

// -----------------------------------------------------------------------------
// Strategy A — walk Python objects directly via PyO3
// -----------------------------------------------------------------------------

struct PyVisitor<'a> {
    tables: BTreeSet<String>,
    events: BTreeSet<String>,
    types: &'a AstTypes,
}

impl<'a> PyVisitor<'a> {
    fn new(types: &'a AstTypes) -> Self {
        Self {
            tables: BTreeSet::new(),
            events: BTreeSet::new(),
            types,
        }
    }

    fn visit(&mut self, py: Python<'_>, node: &Bound<'_, PyAny>) -> PyResult<()> {
        let t = self.types;
        if node.is_exact_instance(t.select_query.bind(py)) {
            for attr in ["select_from", "where", "prewhere", "having"] {
                self.visit_attr(py, node, attr)?;
            }
        } else if node.is_exact_instance(t.select_set_query.bind(py)) {
            self.visit_attr(py, node, "initial_select_query")?;
            for item in node.getattr(intern!(py, "subsequent_select_queries"))?.iter()? {
                self.visit_attr(py, &item?, "select_query")?;
            }
        } else if node.is_exact_instance(t.join_expr.bind(py)) {
            let table = node.getattr(intern!(py, "table"))?;
            if !table.is_none() {
                if table.is_exact_instance(t.field.bind(py)) {
                    let chain = table.getattr(intern!(py, "chain"))?;
                    if let Ok(first) = chain.get_item(0) {
                        if let Ok(s) = first.extract::<String>() {
                            self.tables.insert(s);
                        }
                    }
                } else {
                    self.visit(py, &table)?;
                }
            }
            self.visit_attr(py, node, "next_join")?;
        } else if node.is_exact_instance(t.compare_operation.bind(py)) {
            let op: String = node.getattr(intern!(py, "op"))?.extract()?;
            if op == "==" || op == "in" {
                let left = strip_aliases(py, &node.getattr(intern!(py, "left"))?, t)?;
                let right = strip_aliases(py, &node.getattr(intern!(py, "right"))?, t)?;
                for (field_side, value_side) in &[(&left, &right), (&right, &left)] {
                    if looks_like_event_field(py, field_side, t)? {
                        collect_string_constants(py, value_side, t, &mut self.events)?;
                    }
                }
            }
        } else if node.is_exact_instance(t.and_.bind(py)) || node.is_exact_instance(t.or_.bind(py)) {
            for item in node.getattr(intern!(py, "exprs"))?.iter()? {
                self.visit(py, &item?)?;
            }
        } else if node.is_exact_instance(t.not_.bind(py)) || node.is_exact_instance(t.alias.bind(py)) {
            self.visit_attr(py, node, "expr")?;
        }
        Ok(())
    }

    fn visit_attr(&mut self, py: Python<'_>, node: &Bound<'_, PyAny>, attr: &str) -> PyResult<()> {
        // Match on the attr name to use intern!. The macro requires a literal
        // string at call site, so each branch hands intern! its specific
        // string and benefits from PyO3's per-string caching.
        let inner = match attr {
            "select_from" => node.getattr(intern!(py, "select_from"))?,
            "where" => node.getattr(intern!(py, "where"))?,
            "prewhere" => node.getattr(intern!(py, "prewhere"))?,
            "having" => node.getattr(intern!(py, "having"))?,
            "initial_select_query" => node.getattr(intern!(py, "initial_select_query"))?,
            "select_query" => node.getattr(intern!(py, "select_query"))?,
            "next_join" => node.getattr(intern!(py, "next_join"))?,
            "expr" => node.getattr(intern!(py, "expr"))?,
            other => node.getattr(other)?,
        };
        if !inner.is_none() {
            self.visit(py, &inner)?;
        }
        Ok(())
    }
}

fn strip_aliases<'py>(
    py: Python<'py>,
    expr: &Bound<'py, PyAny>,
    types: &AstTypes,
) -> PyResult<Bound<'py, PyAny>> {
    let mut current = expr.clone();
    while current.is_exact_instance(types.alias.bind(py)) {
        current = current.getattr(intern!(py, "expr"))?;
    }
    Ok(current)
}

fn looks_like_event_field(py: Python<'_>, expr: &Bound<'_, PyAny>, types: &AstTypes) -> PyResult<bool> {
    if !expr.is_exact_instance(types.field.bind(py)) {
        return Ok(false);
    }
    let chain = expr.getattr(intern!(py, "chain"))?;
    let len = chain.len()?;
    if len == 0 {
        return Ok(false);
    }
    let last = chain.get_item(len - 1)?;
    Ok(last.extract::<String>().ok().as_deref() == Some("event"))
}

fn collect_string_constants(
    py: Python<'_>,
    expr: &Bound<'_, PyAny>,
    types: &AstTypes,
    out: &mut BTreeSet<String>,
) -> PyResult<()> {
    if expr.is_exact_instance(types.constant.bind(py)) {
        if let Ok(s) = expr.getattr(intern!(py, "value"))?.extract::<String>() {
            if is_interesting_event(&s) {
                out.insert(s);
            }
        }
    } else if expr.is_exact_instance(types.tuple_.bind(py)) || expr.is_exact_instance(types.array.bind(py)) {
        for item in expr.getattr(intern!(py, "exprs"))?.iter()? {
            collect_string_constants(py, &item?, types, out)?;
        }
    } else if expr.is_exact_instance(types.alias.bind(py)) {
        collect_string_constants(py, &expr.getattr(intern!(py, "expr"))?, types, out)?;
    }
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (query=None))]
fn extract_features_py<'py>(py: Python<'py>, query: Option<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyTuple>> {
    let (tables, events) = match query {
        None => (Vec::new(), Vec::new()),
        Some(q) => {
            let types = ast_types(py)?;
            let mut v = PyVisitor::new(types);
            v.visit(py, &q)?;
            (
                v.tables.into_iter().collect::<Vec<_>>(),
                v.events.into_iter().collect::<Vec<_>>(),
            )
        }
    };
    Ok(PyTuple::new_bound(
        py,
        &[PyList::new_bound(py, &tables), PyList::new_bound(py, &events)],
    ))
}

// -----------------------------------------------------------------------------
// Strategy B — convert to a Rust-native mirror, then walk natively
// -----------------------------------------------------------------------------
//
// The "amortise across N visitors" architecture: pay one Python→Rust
// conversion pass, then run any number of cheap native walks. `convert` does
// the same shape of work the Strategy A visitor does — recursive `getattr` +
// pointer-compare dispatch — just with enum allocation tacked on.

#[derive(Debug)]
enum AstNode {
    SelectQuery {
        select_from: Option<Box<AstNode>>,
        where_clause: Option<Box<AstNode>>,
        prewhere: Option<Box<AstNode>>,
        having: Option<Box<AstNode>>,
    },
    SelectSet {
        children: Vec<AstNode>,
    },
    JoinExpr {
        table: Option<Box<AstNode>>,
        next_join: Option<Box<AstNode>>,
    },
    CompareOperation {
        op: String,
        left: Box<AstNode>,
        right: Box<AstNode>,
    },
    Field {
        chain: Vec<String>,
    },
    Constant {
        value: Option<String>,
    },
    Tuple {
        exprs: Vec<AstNode>,
    },
    Array {
        exprs: Vec<AstNode>,
    },
    Alias {
        expr: Box<AstNode>,
    },
    And {
        exprs: Vec<AstNode>,
    },
    Or {
        exprs: Vec<AstNode>,
    },
    Not {
        expr: Box<AstNode>,
    },
    Other,
}

fn convert(py: Python<'_>, node: &Bound<'_, PyAny>, t: &AstTypes) -> PyResult<AstNode> {
    if node.is_exact_instance(t.select_query.bind(py)) {
        Ok(AstNode::SelectQuery {
            select_from: convert_opt_attr(py, node, intern!(py, "select_from"), t)?,
            where_clause: convert_opt_attr(py, node, intern!(py, "where"), t)?,
            prewhere: convert_opt_attr(py, node, intern!(py, "prewhere"), t)?,
            having: convert_opt_attr(py, node, intern!(py, "having"), t)?,
        })
    } else if node.is_exact_instance(t.select_set_query.bind(py)) {
        let mut children = Vec::new();
        let initial = node.getattr(intern!(py, "initial_select_query"))?;
        if !initial.is_none() {
            children.push(convert(py, &initial, t)?);
        }
        for item in node.getattr(intern!(py, "subsequent_select_queries"))?.iter()? {
            let sub = item?;
            let q = sub.getattr(intern!(py, "select_query"))?;
            if !q.is_none() {
                children.push(convert(py, &q, t)?);
            }
        }
        Ok(AstNode::SelectSet { children })
    } else if node.is_exact_instance(t.join_expr.bind(py)) {
        Ok(AstNode::JoinExpr {
            table: convert_opt_attr(py, node, intern!(py, "table"), t)?,
            next_join: convert_opt_attr(py, node, intern!(py, "next_join"), t)?,
        })
    } else if node.is_exact_instance(t.compare_operation.bind(py)) {
        Ok(AstNode::CompareOperation {
            op: node.getattr(intern!(py, "op"))?.extract()?,
            left: Box::new(convert(py, &node.getattr(intern!(py, "left"))?, t)?),
            right: Box::new(convert(py, &node.getattr(intern!(py, "right"))?, t)?),
        })
    } else if node.is_exact_instance(t.field.bind(py)) {
        let mut chain = Vec::new();
        for item in node.getattr(intern!(py, "chain"))?.iter()? {
            if let Ok(s) = item?.extract::<String>() {
                chain.push(s);
            }
        }
        Ok(AstNode::Field { chain })
    } else if node.is_exact_instance(t.constant.bind(py)) {
        Ok(AstNode::Constant {
            value: node.getattr(intern!(py, "value"))?.extract::<String>().ok(),
        })
    } else if node.is_exact_instance(t.tuple_.bind(py)) {
        Ok(AstNode::Tuple {
            exprs: convert_exprs_list(py, node, intern!(py, "exprs"), t)?,
        })
    } else if node.is_exact_instance(t.array.bind(py)) {
        Ok(AstNode::Array {
            exprs: convert_exprs_list(py, node, intern!(py, "exprs"), t)?,
        })
    } else if node.is_exact_instance(t.alias.bind(py)) {
        Ok(AstNode::Alias {
            expr: Box::new(convert(py, &node.getattr(intern!(py, "expr"))?, t)?),
        })
    } else if node.is_exact_instance(t.and_.bind(py)) {
        Ok(AstNode::And {
            exprs: convert_exprs_list(py, node, intern!(py, "exprs"), t)?,
        })
    } else if node.is_exact_instance(t.or_.bind(py)) {
        Ok(AstNode::Or {
            exprs: convert_exprs_list(py, node, intern!(py, "exprs"), t)?,
        })
    } else if node.is_exact_instance(t.not_.bind(py)) {
        Ok(AstNode::Not {
            expr: Box::new(convert(py, &node.getattr(intern!(py, "expr"))?, t)?),
        })
    } else {
        Ok(AstNode::Other)
    }
}

fn convert_opt_attr(
    py: Python<'_>,
    node: &Bound<'_, PyAny>,
    attr: &Bound<'_, pyo3::types::PyString>,
    types: &AstTypes,
) -> PyResult<Option<Box<AstNode>>> {
    let val = node.getattr(attr)?;
    if val.is_none() {
        Ok(None)
    } else {
        Ok(Some(Box::new(convert(py, &val, types)?)))
    }
}

fn convert_exprs_list(
    py: Python<'_>,
    node: &Bound<'_, PyAny>,
    attr: &Bound<'_, pyo3::types::PyString>,
    types: &AstTypes,
) -> PyResult<Vec<AstNode>> {
    let mut out = Vec::new();
    for item in node.getattr(attr)?.iter()? {
        out.push(convert(py, &item?, types)?);
    }
    Ok(out)
}

struct NativeVisitor {
    tables: BTreeSet<String>,
    events: BTreeSet<String>,
}

impl NativeVisitor {
    fn new() -> Self {
        Self {
            tables: BTreeSet::new(),
            events: BTreeSet::new(),
        }
    }

    fn visit(&mut self, node: &AstNode) {
        match node {
            AstNode::SelectQuery {
                select_from,
                where_clause,
                prewhere,
                having,
            } => {
                for child in [select_from, where_clause, prewhere, having].iter().copied() {
                    if let Some(n) = child {
                        self.visit(n);
                    }
                }
            }
            AstNode::SelectSet { children } => {
                for c in children {
                    self.visit(c);
                }
            }
            AstNode::JoinExpr { table, next_join } => {
                if let Some(t) = table {
                    if let AstNode::Field { chain } = t.as_ref() {
                        if let Some(first) = chain.first() {
                            self.tables.insert(first.clone());
                        }
                    } else {
                        self.visit(t);
                    }
                }
                if let Some(j) = next_join {
                    self.visit(j);
                }
            }
            AstNode::CompareOperation { op, left, right } => {
                if op == "==" || op == "in" {
                    let l = strip_native_aliases(left);
                    let r = strip_native_aliases(right);
                    for (field_side, value_side) in &[(l, r), (r, l)] {
                        if looks_like_native_event_field(field_side) {
                            collect_native_event_strings(value_side, &mut self.events);
                        }
                    }
                }
            }
            AstNode::And { exprs } | AstNode::Or { exprs } => {
                for e in exprs {
                    self.visit(e);
                }
            }
            AstNode::Not { expr } | AstNode::Alias { expr } => self.visit(expr),
            _ => {}
        }
    }
}

fn strip_native_aliases(node: &AstNode) -> &AstNode {
    let mut current = node;
    while let AstNode::Alias { expr } = current {
        current = expr;
    }
    current
}

fn looks_like_native_event_field(node: &AstNode) -> bool {
    matches!(node, AstNode::Field { chain } if chain.last().map(|s| s.as_str()) == Some("event"))
}

fn collect_native_event_strings(node: &AstNode, out: &mut BTreeSet<String>) {
    match node {
        AstNode::Constant { value: Some(s) } if is_interesting_event(s) => {
            out.insert(s.clone());
        }
        AstNode::Tuple { exprs } | AstNode::Array { exprs } => {
            for e in exprs {
                collect_native_event_strings(e, out);
            }
        }
        AstNode::Alias { expr } => collect_native_event_strings(expr, out),
        _ => {}
    }
}

#[pyfunction]
#[pyo3(signature = (query=None))]
fn extract_features_via_mirror<'py>(
    py: Python<'py>,
    query: Option<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyTuple>> {
    let (tables, events) = match query {
        None => (Vec::new(), Vec::new()),
        Some(q) => {
            let types = ast_types(py)?;
            let mirror = convert(py, &q, types)?;
            let mut v = NativeVisitor::new();
            v.visit(&mirror);
            (
                v.tables.into_iter().collect::<Vec<_>>(),
                v.events.into_iter().collect::<Vec<_>>(),
            )
        }
    };
    Ok(PyTuple::new_bound(
        py,
        &[PyList::new_bound(py, &tables), PyList::new_bound(py, &events)],
    ))
}

// Opaque mirror handle returned to Python so the bench can measure convert
// and visit phases separately.
#[pyclass]
struct AstMirror {
    inner: AstNode,
}

#[pyfunction]
fn to_mirror(py: Python<'_>, query: Bound<'_, PyAny>) -> PyResult<AstMirror> {
    let types = ast_types(py)?;
    Ok(AstMirror {
        inner: convert(py, &query, types)?,
    })
}

#[pyfunction]
fn extract_features_from_mirror<'py>(py: Python<'py>, mirror: &AstMirror) -> PyResult<Bound<'py, PyTuple>> {
    let mut v = NativeVisitor::new();
    v.visit(&mirror.inner);
    let tables = v.tables.into_iter().collect::<Vec<_>>();
    let events = v.events.into_iter().collect::<Vec<_>>();
    Ok(PyTuple::new_bound(
        py,
        &[PyList::new_bound(py, &tables), PyList::new_bound(py, &events)],
    ))
}

#[pymodule]
fn hogql_visitors_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_features_py, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_via_mirror, m)?)?;
    m.add_function(wrap_pyfunction!(to_mirror, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_from_mirror, m)?)?;
    m.add_class::<AstMirror>()?;
    Ok(())
}
