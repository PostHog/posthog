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

use pyo3::ffi::{PyMemberDef, PyObject, PyTypeObject, Py_INCREF, Py_ssize_t};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::{PyList, PyTuple, PyType};
use std::collections::BTreeSet;
use std::os::raw::c_char;

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
// Strategy A-slots — direct slot-offset reads instead of getattr
// -----------------------------------------------------------------------------
//
// `@dataclass(slots=True)` lays each instance out as a C struct with a
// known-at-class-creation offset per field. PyO3's `getattr(intern!())` still
// walks the type's MRO to find the slot descriptor on every call. We can
// skip that by extracting each slot's offset once from its
// `member_descriptor` and reading the PyObject pointer directly.
//
// One small piece of `unsafe` glue: PyO3 exposes `PyMemberDef` (which has
// `.offset`), but doesn't expose the `PyMemberDescrObject` layout that
// holds the `PyMemberDef *` pointer. So we mirror that struct here. The
// layout has been stable since Python 3.12.

#[repr(C)]
struct CMemberDescrObject {
    ob_refcnt: Py_ssize_t,
    ob_type: *mut PyTypeObject,
    // PyDescrObject head:
    d_type: *mut PyTypeObject,
    d_name: *mut PyObject,
    d_qualname: *mut PyObject,
    // PyMemberDescrObject's payload — the thing we want:
    d_member: *mut PyMemberDef,
}

/// Pull the slot offset out of a `member_descriptor` for the named attribute.
/// Returns `None` if the class doesn't expose a member descriptor by that
/// name (e.g. inherited from a non-slots base, or `cached_property`, etc.).
fn slot_offset(cls: &Bound<'_, PyType>, attr: &str) -> Option<isize> {
    let descr = cls.getattr(attr).ok()?;
    // Confirm it really is a member_descriptor before reinterpreting.
    let descr_type = descr.get_type();
    let descr_type_name = descr_type.name().ok()?;
    if descr_type_name.to_str().ok()? != "member_descriptor" {
        return None;
    }
    unsafe {
        let descr_ptr = descr.as_ptr() as *const CMemberDescrObject;
        let member_def = (*descr_ptr).d_member;
        if member_def.is_null() {
            return None;
        }
        Some((*member_def).offset)
    }
}

/// Read a slot at a known offset from a Python object. Returns `None` if the
/// slot is unset (NULL) or if it holds `Py_None`. Callers expecting `None`
/// values as a real signal should use `read_slot_raw` instead.
unsafe fn read_slot<'py>(node: &Bound<'py, PyAny>, offset: isize) -> Option<Bound<'py, PyAny>> {
    let node_ptr = node.as_ptr() as *const c_char;
    let field_ptr = node_ptr.byte_offset(offset) as *const *mut PyObject;
    let raw = *field_ptr;
    if raw.is_null() {
        return None;
    }
    // Treat `None` as missing — matches how Strategy A's `visit_attr` already
    // checks `inner.is_none()` before recursing.
    if raw == pyo3::ffi::Py_None() {
        return None;
    }
    Py_INCREF(raw);
    Some(Bound::from_owned_ptr(node.py(), raw))
}

/// Same as `read_slot` but returns `Py_None` as a real value instead of
/// short-circuiting it. Used for `op` and `value` fields where None is a
/// valid distinct case.
unsafe fn read_slot_raw<'py>(node: &Bound<'py, PyAny>, offset: isize) -> Option<Bound<'py, PyAny>> {
    let node_ptr = node.as_ptr() as *const c_char;
    let field_ptr = node_ptr.byte_offset(offset) as *const *mut PyObject;
    let raw = *field_ptr;
    if raw.is_null() {
        return None;
    }
    Py_INCREF(raw);
    Some(Bound::from_owned_ptr(node.py(), raw))
}

// Per-class slot offset caches. Each variant only fills in the fields its
// branch of the visitor reads.

#[derive(Default)]
struct SelectQueryOffsets {
    select_from: isize,
    where_: isize,
    prewhere: isize,
    having: isize,
}

#[derive(Default)]
struct SelectSetQueryOffsets {
    initial_select_query: isize,
    subsequent_select_queries: isize,
}

#[derive(Default)]
struct SelectSetNodeOffsets {
    select_query: isize,
}

#[derive(Default)]
struct JoinExprOffsets {
    table: isize,
    next_join: isize,
}

#[derive(Default)]
struct CompareOperationOffsets {
    op: isize,
    left: isize,
    right: isize,
}

#[derive(Default)]
struct FieldOffsets {
    chain: isize,
}

#[derive(Default)]
struct ExprsContainerOffsets {
    // for And / Or / Tuple / Array
    exprs: isize,
}

#[derive(Default)]
struct ExprWrapperOffsets {
    // for Not / Alias
    expr: isize,
}

#[derive(Default)]
struct ConstantOffsets {
    value: isize,
}

struct AstOffsets {
    select_query: SelectQueryOffsets,
    select_set_query: SelectSetQueryOffsets,
    select_set_node: SelectSetNodeOffsets,
    join_expr: JoinExprOffsets,
    compare_operation: CompareOperationOffsets,
    field: FieldOffsets,
    and_: ExprsContainerOffsets,
    or_: ExprsContainerOffsets,
    tuple_: ExprsContainerOffsets,
    array: ExprsContainerOffsets,
    not_: ExprWrapperOffsets,
    alias: ExprWrapperOffsets,
    constant: ConstantOffsets,
}

static AST_OFFSETS: GILOnceCell<AstOffsets> = GILOnceCell::new();

fn ast_offsets<'py>(py: Python<'py>) -> PyResult<&'py AstOffsets> {
    AST_OFFSETS.get_or_try_init(py, || {
        let m = py.import_bound("posthog.hogql.ast")?;
        let off = |name: &str, attr: &str| -> PyResult<isize> {
            let cls = m.getattr(name)?.downcast::<PyType>()?.clone();
            slot_offset(&cls, attr).ok_or_else(|| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "couldn't extract slot offset for {name}.{attr} — class may not be @dataclass(slots=True)"
                ))
            })
        };
        Ok(AstOffsets {
            select_query: SelectQueryOffsets {
                select_from: off("SelectQuery", "select_from")?,
                where_: off("SelectQuery", "where")?,
                prewhere: off("SelectQuery", "prewhere")?,
                having: off("SelectQuery", "having")?,
            },
            select_set_query: SelectSetQueryOffsets {
                initial_select_query: off("SelectSetQuery", "initial_select_query")?,
                subsequent_select_queries: off("SelectSetQuery", "subsequent_select_queries")?,
            },
            select_set_node: SelectSetNodeOffsets {
                select_query: off("SelectSetNode", "select_query")?,
            },
            join_expr: JoinExprOffsets {
                table: off("JoinExpr", "table")?,
                next_join: off("JoinExpr", "next_join")?,
            },
            compare_operation: CompareOperationOffsets {
                op: off("CompareOperation", "op")?,
                left: off("CompareOperation", "left")?,
                right: off("CompareOperation", "right")?,
            },
            field: FieldOffsets {
                chain: off("Field", "chain")?,
            },
            and_: ExprsContainerOffsets {
                exprs: off("And", "exprs")?,
            },
            or_: ExprsContainerOffsets {
                exprs: off("Or", "exprs")?,
            },
            tuple_: ExprsContainerOffsets {
                exprs: off("Tuple", "exprs")?,
            },
            array: ExprsContainerOffsets {
                exprs: off("Array", "exprs")?,
            },
            not_: ExprWrapperOffsets {
                expr: off("Not", "expr")?,
            },
            alias: ExprWrapperOffsets {
                expr: off("Alias", "expr")?,
            },
            constant: ConstantOffsets {
                value: off("Constant", "value")?,
            },
        })
    })
}

struct SlotsVisitor<'a> {
    tables: BTreeSet<String>,
    events: BTreeSet<String>,
    types: &'a AstTypes,
    offsets: &'a AstOffsets,
}

impl<'a> SlotsVisitor<'a> {
    fn new(types: &'a AstTypes, offsets: &'a AstOffsets) -> Self {
        Self {
            tables: BTreeSet::new(),
            events: BTreeSet::new(),
            types,
            offsets,
        }
    }

    fn visit(&mut self, py: Python<'_>, node: &Bound<'_, PyAny>) -> PyResult<()> {
        let t = self.types;
        let o = self.offsets;
        unsafe {
            if node.is_exact_instance(t.select_query.bind(py)) {
                for offset in [
                    o.select_query.select_from,
                    o.select_query.where_,
                    o.select_query.prewhere,
                    o.select_query.having,
                ] {
                    if let Some(child) = read_slot(node, offset) {
                        self.visit(py, &child)?;
                    }
                }
            } else if node.is_exact_instance(t.select_set_query.bind(py)) {
                if let Some(initial) = read_slot(node, o.select_set_query.initial_select_query) {
                    self.visit(py, &initial)?;
                }
                if let Some(subs) = read_slot(node, o.select_set_query.subsequent_select_queries) {
                    for item in subs.iter()? {
                        let sub = item?;
                        if let Some(q) = read_slot(&sub, o.select_set_node.select_query) {
                            self.visit(py, &q)?;
                        }
                    }
                }
            } else if node.is_exact_instance(t.join_expr.bind(py)) {
                if let Some(table) = read_slot(node, o.join_expr.table) {
                    if table.is_exact_instance(t.field.bind(py)) {
                        if let Some(chain) = read_slot(&table, o.field.chain) {
                            if let Ok(first) = chain.get_item(0) {
                                if let Ok(s) = first.extract::<String>() {
                                    self.tables.insert(s);
                                }
                            }
                        }
                    } else {
                        self.visit(py, &table)?;
                    }
                }
                if let Some(next_join) = read_slot(node, o.join_expr.next_join) {
                    self.visit(py, &next_join)?;
                }
            } else if node.is_exact_instance(t.compare_operation.bind(py)) {
                if let Some(op_obj) = read_slot_raw(node, o.compare_operation.op) {
                    let op: String = op_obj.extract()?;
                    if op == "==" || op == "in" {
                        // left/right are required fields; treat None as a typing
                        // edge case but normal extraction handles that.
                        let left_raw = read_slot_raw(node, o.compare_operation.left);
                        let right_raw = read_slot_raw(node, o.compare_operation.right);
                        if let (Some(l), Some(r)) = (left_raw, right_raw) {
                            let left = strip_aliases_slots(py, &l, o, t)?;
                            let right = strip_aliases_slots(py, &r, o, t)?;
                            for (field_side, value_side) in &[(&left, &right), (&right, &left)] {
                                if looks_like_event_field_slots(py, field_side, o, t)? {
                                    collect_string_constants_slots(py, value_side, o, t, &mut self.events)?;
                                }
                            }
                        }
                    }
                }
            } else if node.is_exact_instance(t.and_.bind(py)) {
                if let Some(exprs) = read_slot(node, o.and_.exprs) {
                    for item in exprs.iter()? {
                        self.visit(py, &item?)?;
                    }
                }
            } else if node.is_exact_instance(t.or_.bind(py)) {
                if let Some(exprs) = read_slot(node, o.or_.exprs) {
                    for item in exprs.iter()? {
                        self.visit(py, &item?)?;
                    }
                }
            } else if node.is_exact_instance(t.not_.bind(py)) {
                if let Some(expr) = read_slot(node, o.not_.expr) {
                    self.visit(py, &expr)?;
                }
            } else if node.is_exact_instance(t.alias.bind(py)) {
                if let Some(expr) = read_slot(node, o.alias.expr) {
                    self.visit(py, &expr)?;
                }
            }
        }
        Ok(())
    }
}

fn strip_aliases_slots<'py>(
    py: Python<'py>,
    expr: &Bound<'py, PyAny>,
    offsets: &AstOffsets,
    types: &AstTypes,
) -> PyResult<Bound<'py, PyAny>> {
    let mut current = expr.clone();
    while current.is_exact_instance(types.alias.bind(py)) {
        let next = unsafe { read_slot_raw(&current, offsets.alias.expr) };
        match next {
            Some(n) => current = n,
            None => break,
        }
    }
    Ok(current)
}

fn looks_like_event_field_slots(
    py: Python<'_>,
    expr: &Bound<'_, PyAny>,
    offsets: &AstOffsets,
    types: &AstTypes,
) -> PyResult<bool> {
    if !expr.is_exact_instance(types.field.bind(py)) {
        return Ok(false);
    }
    let chain = match unsafe { read_slot(expr, offsets.field.chain) } {
        Some(c) => c,
        None => return Ok(false),
    };
    let len = chain.len()?;
    if len == 0 {
        return Ok(false);
    }
    let last = chain.get_item(len - 1)?;
    Ok(last.extract::<String>().ok().as_deref() == Some("event"))
}

fn collect_string_constants_slots(
    py: Python<'_>,
    expr: &Bound<'_, PyAny>,
    offsets: &AstOffsets,
    types: &AstTypes,
    out: &mut BTreeSet<String>,
) -> PyResult<()> {
    unsafe {
        if expr.is_exact_instance(types.constant.bind(py)) {
            if let Some(v) = read_slot_raw(expr, offsets.constant.value) {
                if let Ok(s) = v.extract::<String>() {
                    if is_interesting_event(&s) {
                        out.insert(s);
                    }
                }
            }
        } else if expr.is_exact_instance(types.tuple_.bind(py)) {
            if let Some(exprs) = read_slot(expr, offsets.tuple_.exprs) {
                for item in exprs.iter()? {
                    collect_string_constants_slots(py, &item?, offsets, types, out)?;
                }
            }
        } else if expr.is_exact_instance(types.array.bind(py)) {
            if let Some(exprs) = read_slot(expr, offsets.array.exprs) {
                for item in exprs.iter()? {
                    collect_string_constants_slots(py, &item?, offsets, types, out)?;
                }
            }
        } else if expr.is_exact_instance(types.alias.bind(py)) {
            if let Some(inner) = read_slot(expr, offsets.alias.expr) {
                collect_string_constants_slots(py, &inner, offsets, types, out)?;
            }
        }
    }
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (query=None))]
fn extract_features_py_slots<'py>(
    py: Python<'py>,
    query: Option<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyTuple>> {
    let (tables, events) = match query {
        None => (Vec::new(), Vec::new()),
        Some(q) => {
            let types = ast_types(py)?;
            let offsets = ast_offsets(py)?;
            let mut v = SlotsVisitor::new(types, offsets);
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

// ---- B-slots: same conversion shape, using direct slot-offset reads ----
//
// Mirror of `convert`/`convert_opt_attr`/`convert_exprs_list` that uses the
// cached `AstOffsets` to read each field via raw pointer arithmetic instead
// of PyO3 `getattr`. Same trick A-slots uses, applied symmetrically to the
// Python → Rust mirror conversion pass.

fn convert_slots(py: Python<'_>, node: &Bound<'_, PyAny>, t: &AstTypes, o: &AstOffsets) -> PyResult<AstNode> {
    unsafe {
        if node.is_exact_instance(t.select_query.bind(py)) {
            Ok(AstNode::SelectQuery {
                select_from: convert_opt_offset(py, node, o.select_query.select_from, t, o)?,
                where_clause: convert_opt_offset(py, node, o.select_query.where_, t, o)?,
                prewhere: convert_opt_offset(py, node, o.select_query.prewhere, t, o)?,
                having: convert_opt_offset(py, node, o.select_query.having, t, o)?,
            })
        } else if node.is_exact_instance(t.select_set_query.bind(py)) {
            let mut children = Vec::new();
            if let Some(initial) = read_slot(node, o.select_set_query.initial_select_query) {
                children.push(convert_slots(py, &initial, t, o)?);
            }
            if let Some(subs) = read_slot(node, o.select_set_query.subsequent_select_queries) {
                for item in subs.iter()? {
                    let sub = item?;
                    if let Some(q) = read_slot(&sub, o.select_set_node.select_query) {
                        children.push(convert_slots(py, &q, t, o)?);
                    }
                }
            }
            Ok(AstNode::SelectSet { children })
        } else if node.is_exact_instance(t.join_expr.bind(py)) {
            Ok(AstNode::JoinExpr {
                table: convert_opt_offset(py, node, o.join_expr.table, t, o)?,
                next_join: convert_opt_offset(py, node, o.join_expr.next_join, t, o)?,
            })
        } else if node.is_exact_instance(t.compare_operation.bind(py)) {
            // `op` is read raw because the value can semantically be anything
            // (None included). Left/right are required Expr fields.
            let op_obj = read_slot_raw(node, o.compare_operation.op)
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("missing op"))?;
            let left = read_slot_raw(node, o.compare_operation.left)
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("missing left"))?;
            let right = read_slot_raw(node, o.compare_operation.right)
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("missing right"))?;
            Ok(AstNode::CompareOperation {
                op: op_obj.extract()?,
                left: Box::new(convert_slots(py, &left, t, o)?),
                right: Box::new(convert_slots(py, &right, t, o)?),
            })
        } else if node.is_exact_instance(t.field.bind(py)) {
            let mut chain = Vec::new();
            if let Some(c) = read_slot(node, o.field.chain) {
                for item in c.iter()? {
                    if let Ok(s) = item?.extract::<String>() {
                        chain.push(s);
                    }
                }
            }
            Ok(AstNode::Field { chain })
        } else if node.is_exact_instance(t.constant.bind(py)) {
            let value = read_slot_raw(node, o.constant.value).and_then(|v| v.extract::<String>().ok());
            Ok(AstNode::Constant { value })
        } else if node.is_exact_instance(t.tuple_.bind(py)) {
            Ok(AstNode::Tuple {
                exprs: convert_exprs_offset(py, node, o.tuple_.exprs, t, o)?,
            })
        } else if node.is_exact_instance(t.array.bind(py)) {
            Ok(AstNode::Array {
                exprs: convert_exprs_offset(py, node, o.array.exprs, t, o)?,
            })
        } else if node.is_exact_instance(t.alias.bind(py)) {
            let inner = read_slot_raw(node, o.alias.expr)
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("missing alias.expr"))?;
            Ok(AstNode::Alias {
                expr: Box::new(convert_slots(py, &inner, t, o)?),
            })
        } else if node.is_exact_instance(t.and_.bind(py)) {
            Ok(AstNode::And {
                exprs: convert_exprs_offset(py, node, o.and_.exprs, t, o)?,
            })
        } else if node.is_exact_instance(t.or_.bind(py)) {
            Ok(AstNode::Or {
                exprs: convert_exprs_offset(py, node, o.or_.exprs, t, o)?,
            })
        } else if node.is_exact_instance(t.not_.bind(py)) {
            let inner = read_slot_raw(node, o.not_.expr)
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("missing not.expr"))?;
            Ok(AstNode::Not {
                expr: Box::new(convert_slots(py, &inner, t, o)?),
            })
        } else {
            Ok(AstNode::Other)
        }
    }
}

fn convert_opt_offset(
    py: Python<'_>,
    node: &Bound<'_, PyAny>,
    offset: isize,
    types: &AstTypes,
    offsets: &AstOffsets,
) -> PyResult<Option<Box<AstNode>>> {
    let val = match unsafe { read_slot(node, offset) } {
        Some(v) => v,
        None => return Ok(None),
    };
    Ok(Some(Box::new(convert_slots(py, &val, types, offsets)?)))
}

fn convert_exprs_offset(
    py: Python<'_>,
    node: &Bound<'_, PyAny>,
    offset: isize,
    types: &AstTypes,
    offsets: &AstOffsets,
) -> PyResult<Vec<AstNode>> {
    let mut out = Vec::new();
    if let Some(exprs) = unsafe { read_slot(node, offset) } {
        for item in exprs.iter()? {
            out.push(convert_slots(py, &item?, types, offsets)?);
        }
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
fn to_mirror_slots(py: Python<'_>, query: Bound<'_, PyAny>) -> PyResult<AstMirror> {
    let types = ast_types(py)?;
    let offsets = ast_offsets(py)?;
    Ok(AstMirror {
        inner: convert_slots(py, &query, types, offsets)?,
    })
}

#[pyfunction]
#[pyo3(signature = (query=None))]
fn extract_features_via_mirror_slots<'py>(
    py: Python<'py>,
    query: Option<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyTuple>> {
    let (tables, events) = match query {
        None => (Vec::new(), Vec::new()),
        Some(q) => {
            let types = ast_types(py)?;
            let offsets = ast_offsets(py)?;
            let mirror = convert_slots(py, &q, types, offsets)?;
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
    m.add_function(wrap_pyfunction!(extract_features_py_slots, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_via_mirror, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_via_mirror_slots, m)?)?;
    m.add_function(wrap_pyfunction!(to_mirror, m)?)?;
    m.add_function(wrap_pyfunction!(to_mirror_slots, m)?)?;
    m.add_function(wrap_pyfunction!(extract_features_from_mirror, m)?)?;
    m.add_class::<AstMirror>()?;
    Ok(())
}
