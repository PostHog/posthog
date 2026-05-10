//! Rust-backed feature extractor for the HogQL AST.
//!
//! Two implementations exposed for direct benchmarking:
//!
//! * `extract_features_py(query)` — walks Python AST objects in place via
//!   PyO3. Each `getattr` is a Python C-API call, so per-node cost is similar
//!   to Python; the win is ~2-3× from skipping the interpreter dispatch loop.
//!
//! * `extract_features_via_mirror(query)` — converts the Python AST to a
//!   Rust-native mirror once, then walks the mirror. Single-visitor break-even
//!   is ~2 visitors over the same tree; for the multi-visitor pipeline
//!   (Resolver, optimizer pass, printer pass, …) this is the architecture
//!   that actually pays off.
//!
//! Both return `(tables, events)` as Python lists; the Python wrapper
//! repackages them into the `HogQLFeatures` Pydantic model.

use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};
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
// Strategy A — walk Python objects directly via PyO3
// -----------------------------------------------------------------------------
//
// Mirrors the Python `HogQLFeatureExtractor`. Each step is a Python attribute
// access, so this is bottlenecked by the same PyO3 ↔ CPython transitions as
// the Python implementation, just without Python-level dispatch overhead.

struct PyVisitor {
    tables: BTreeSet<String>,
    events: BTreeSet<String>,
}

impl PyVisitor {
    fn new() -> Self {
        Self {
            tables: BTreeSet::new(),
            events: BTreeSet::new(),
        }
    }

    fn visit(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        // Single dispatch on Python type name. Faster than full isinstance —
        // we don't need Python's MRO traversal; the AST type names are stable.
        let cls_name = node.get_type().name()?;
        match cls_name.to_str()? {
            "SelectQuery" => self.visit_select(node)?,
            "SelectSetQuery" => self.visit_select_set(node)?,
            "JoinExpr" => self.visit_join(node)?,
            "CompareOperation" => self.visit_compare(node)?,
            "And" | "Or" => self.visit_exprs_list(node)?,
            "Not" => self.visit_attr(node, "expr")?,
            "Alias" => self.visit_attr(node, "expr")?,
            // Constants, fields, calls etc. don't need recursion for our purposes
            _ => {}
        }
        Ok(())
    }

    fn visit_attr(&mut self, node: &Bound<'_, PyAny>, attr: &str) -> PyResult<()> {
        let inner = node.getattr(attr)?;
        if !inner.is_none() {
            self.visit(&inner)?;
        }
        Ok(())
    }

    fn visit_exprs_list(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        let exprs = node.getattr("exprs")?;
        for item in exprs.iter()? {
            self.visit(&item?)?;
        }
        Ok(())
    }

    fn visit_select(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        for attr in &["select_from", "where", "prewhere", "having"] {
            self.visit_attr(node, attr)?;
        }
        // Skipping select / group_by / order_by for the PoC — they don't carry
        // the join/event signal we care about.
        Ok(())
    }

    fn visit_select_set(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        self.visit_attr(node, "initial_select_query")?;
        let subs = node.getattr("subsequent_select_queries")?;
        for item in subs.iter()? {
            let sub = item?;
            self.visit_attr(&sub, "select_query")?;
        }
        Ok(())
    }

    fn visit_join(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        let table = node.getattr("table")?;
        if !table.is_none() {
            // Capture table name when `table` is a Field with a string chain head
            if table.get_type().name()?.to_str()? == "Field" {
                let chain = table.getattr("chain")?;
                if let Ok(first) = chain.get_item(0) {
                    if let Ok(s) = first.extract::<String>() {
                        self.tables.insert(s);
                    }
                }
            } else {
                self.visit(&table)?;
            }
        }
        self.visit_attr(node, "next_join")?;
        Ok(())
    }

    fn visit_compare(&mut self, node: &Bound<'_, PyAny>) -> PyResult<()> {
        let op_obj = node.getattr("op")?;
        let op: String = op_obj.extract()?;
        if op == "==" || op == "in" {
            let left = strip_aliases(&node.getattr("left")?)?;
            let right = strip_aliases(&node.getattr("right")?)?;
            for (field_side, value_side) in &[(&left, &right), (&right, &left)] {
                if looks_like_event_field(field_side)? {
                    collect_string_constants(value_side, &mut self.events)?;
                }
            }
        }
        Ok(())
    }
}

fn strip_aliases<'py>(expr: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let mut current = expr.clone();
    while current.get_type().name()?.to_str()? == "Alias" {
        current = current.getattr("expr")?;
    }
    Ok(current)
}

fn looks_like_event_field(expr: &Bound<'_, PyAny>) -> PyResult<bool> {
    if expr.get_type().name()?.to_str()? != "Field" {
        return Ok(false);
    }
    let chain = expr.getattr("chain")?;
    let len = chain.len()?;
    if len == 0 {
        return Ok(false);
    }
    let last = chain.get_item(len - 1)?;
    Ok(last.extract::<String>().ok().as_deref() == Some("event"))
}

fn collect_string_constants(expr: &Bound<'_, PyAny>, out: &mut BTreeSet<String>) -> PyResult<()> {
    let cls = expr.get_type().name()?;
    match cls.to_str()? {
        "Constant" => {
            if let Ok(s) = expr.getattr("value")?.extract::<String>() {
                if is_interesting_event(&s) {
                    out.insert(s);
                }
            }
        }
        "Tuple" | "Array" => {
            for item in expr.getattr("exprs")?.iter()? {
                collect_string_constants(&item?, out)?;
            }
        }
        "Alias" => {
            collect_string_constants(&expr.getattr("expr")?, out)?;
        }
        _ => {}
    }
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (query=None))]
fn extract_features_py<'py>(
    py: Python<'py>,
    query: Option<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyTuple>> {
    let (tables, events) = match query {
        None => (Vec::new(), Vec::new()),
        Some(q) => {
            let mut v = PyVisitor::new();
            v.visit(&q)?;
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
// The "amortize across N visitors" architecture: pay one Python→Rust conversion
// pass, then run any number of cheap native walks. Single-visitor break-even
// vs strategy A is around 2 visitors. The conversion is intentionally minimal
// — only the node kinds the feature extractor cares about retain structure;
// the rest collapse to `Other`.

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

fn convert(node: &Bound<'_, PyAny>) -> PyResult<AstNode> {
    let cls = node.get_type().name()?;
    Ok(match cls.to_str()? {
        "SelectQuery" => AstNode::SelectQuery {
            select_from: convert_opt_attr(node, "select_from")?,
            where_clause: convert_opt_attr(node, "where")?,
            prewhere: convert_opt_attr(node, "prewhere")?,
            having: convert_opt_attr(node, "having")?,
        },
        "SelectSetQuery" => {
            let mut children = Vec::new();
            let initial = node.getattr("initial_select_query")?;
            if !initial.is_none() {
                children.push(convert(&initial)?);
            }
            for item in node.getattr("subsequent_select_queries")?.iter()? {
                let sub = item?;
                let q = sub.getattr("select_query")?;
                if !q.is_none() {
                    children.push(convert(&q)?);
                }
            }
            AstNode::SelectSet { children }
        }
        "JoinExpr" => AstNode::JoinExpr {
            table: convert_opt_attr(node, "table")?,
            next_join: convert_opt_attr(node, "next_join")?,
        },
        "CompareOperation" => AstNode::CompareOperation {
            op: node.getattr("op")?.extract()?,
            left: Box::new(convert(&node.getattr("left")?)?),
            right: Box::new(convert(&node.getattr("right")?)?),
        },
        "Field" => {
            let mut chain = Vec::new();
            for item in node.getattr("chain")?.iter()? {
                if let Ok(s) = item?.extract::<String>() {
                    chain.push(s);
                }
            }
            AstNode::Field { chain }
        }
        "Constant" => AstNode::Constant {
            value: node.getattr("value")?.extract::<String>().ok(),
        },
        "Tuple" => AstNode::Tuple {
            exprs: convert_exprs_list(node, "exprs")?,
        },
        "Array" => AstNode::Array {
            exprs: convert_exprs_list(node, "exprs")?,
        },
        "Alias" => AstNode::Alias {
            expr: Box::new(convert(&node.getattr("expr")?)?),
        },
        "And" => AstNode::And {
            exprs: convert_exprs_list(node, "exprs")?,
        },
        "Or" => AstNode::Or {
            exprs: convert_exprs_list(node, "exprs")?,
        },
        "Not" => AstNode::Not {
            expr: Box::new(convert(&node.getattr("expr")?)?),
        },
        _ => AstNode::Other,
    })
}

fn convert_opt_attr(node: &Bound<'_, PyAny>, attr: &str) -> PyResult<Option<Box<AstNode>>> {
    let val = node.getattr(attr)?;
    if val.is_none() {
        Ok(None)
    } else {
        Ok(Some(Box::new(convert(&val)?)))
    }
}

fn convert_exprs_list(node: &Bound<'_, PyAny>, attr: &str) -> PyResult<Vec<AstNode>> {
    let mut out = Vec::new();
    for item in node.getattr(attr)?.iter()? {
        out.push(convert(&item?)?);
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
            let mirror = convert(&q)?;
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

#[pymodule]
fn hogql_visitors_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_features_py, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_via_mirror, m)?)?;
    Ok(())
}
