//! Rust core of kea-wasm.
//!
//! The JavaScript shell keeps the public kea API. This crate owns the parts of kea that are
//! bookkeeping or tree walks:
//!
//! - the reducer tree (`attachReducer`, `detachReducer`, `regenerateRootReducer`),
//! - the compiled root reducer that runs on every dispatch,
//! - the per-logic reducer combination (`combineKeaReducers(logic.reducers)`),
//! - mount reference counts,
//! - the listener index that the listeners middleware reads on every dispatch,
//! - action type names.
//!
//! The compiled reducer tree records which action types can change each subtree. When the
//! incoming state of a subtree is the state that the subtree returned last time, and the
//! action can not change the subtree, the subtree returns its state without a call into
//! JavaScript. Subtrees with reducers that kea did not generate ("opaque" reducers) always run.
//!
//! Two rules keep the engine safe to embed:
//!
//! - The engine holds no reference to a logic's functions. Each logic keeps them in a JavaScript
//!   array ("slots"), and the engine stores slot indices. The engine holds the slot array only
//!   while the logic's reducer is attached, so an unmounted logic can be garbage collected.
//! - The engine never calls listeners. Listener chains (listener -> dispatch -> listener) can
//!   recurse deeply, and a JavaScript stack overflow must not unwind through WebAssembly frames.

mod omap;

use js_sys::{Array, Object};
use omap::OMap;
use std::cell::{Cell, OnceCell, RefCell};
use std::collections::{HashMap, HashSet};
use std::rc::Rc;
use wasm_bindgen::prelude::*;

#[wasm_bindgen(inline_js = r#"
export function js_get(o, k) { return o[k] }
export function js_set(o, k, v) { o[k] = v }
export function js_keys_len(o) { return Object.keys(o).length }
export function js_new_obj() { return {} }
export function js_call3(f, a, b, c) { return f(a, b, c) }
export function js_call_slot3(slots, i, a, b, c) { return slots[i](a, b, c) }
export function js_type_key(action) {
  if (!action) return undefined
  const t = action.type
  return typeof t === 'symbol' ? undefined : String(t)
}
export function js_reducer_undefined_error(key, action) {
  return new Error(`[KEA] Reducer "${key}" returned undefined for action "${action && action.type}"`)
}
export function js_whitelist_error(pathStart) {
  return new Error(`[KEA] Can not start reducer's path with "${pathStart}"! Please add it to the whitelist`)
}
"#)]
extern "C" {
    #[wasm_bindgen(catch)]
    fn js_get(o: &JsValue, k: &JsValue) -> Result<JsValue, JsValue>;
    #[wasm_bindgen(catch)]
    fn js_set(o: &JsValue, k: &JsValue, v: &JsValue) -> Result<(), JsValue>;
    #[wasm_bindgen(catch)]
    fn js_keys_len(o: &JsValue) -> Result<u32, JsValue>;
    fn js_new_obj() -> JsValue;
    #[wasm_bindgen(catch)]
    fn js_call3(f: &JsValue, a: &JsValue, b: &JsValue, c: &JsValue) -> Result<JsValue, JsValue>;
    #[wasm_bindgen(catch)]
    fn js_call_slot3(slots: &JsValue, i: u32, a: &JsValue, b: &JsValue, c: &JsValue) -> Result<JsValue, JsValue>;
    fn js_type_key(action: &JsValue) -> Option<String>;
    fn js_reducer_undefined_error(key: &JsValue, action: &JsValue) -> JsValue;
    fn js_whitelist_error(path_start: &str) -> JsValue;
}

// ---------------------------------------------------------------------------------------------
// Global state shared by all engines
// ---------------------------------------------------------------------------------------------

thread_local! {
    /// Action types and reducer mapping keys get a small integer id. The table only grows from
    /// code-defined strings: dispatch looks up types and never inserts them.
    static INTERNER: RefCell<HashMap<String, u32>> = RefCell::new(HashMap::new());
    /// A change to a mounted logic's reducers increments this value. Cached summaries and
    /// cached states with an older value are not used.
    static EPOCH: Cell<u32> = const { Cell::new(1) };
    static KEY_TYPE: JsValue = JsValue::from_str("type");
    static KEY_PAYLOAD: JsValue = JsValue::from_str("payload");
    static KEY_META: JsValue = JsValue::from_str("meta");
    static STATS: RefCell<Stats> = RefCell::new(Stats::default());
    static NEXT_ENGINE_ID: Cell<u32> = const { Cell::new(1) };
}

#[derive(Default)]
struct Stats {
    dispatches: f64,
    nodes_skipped: f64,
    nodes_run: f64,
    js_reducer_calls: f64,
    generated_reducers_skipped: f64,
}

fn intern(s: &str) -> u32 {
    INTERNER.with(|t| {
        let mut t = t.borrow_mut();
        if let Some(id) = t.get(s) {
            return *id;
        }
        let id = t.len() as u32 + 1;
        t.insert(s.to_string(), id);
        id
    })
}

fn lookup(s: &str) -> Option<u32> {
    INTERNER.with(|t| t.borrow().get(s).copied())
}

fn epoch() -> u32 {
    EPOCH.with(|e| e.get())
}

fn bump_epoch() {
    EPOCH.with(|e| e.set(e.get().wrapping_add(1).max(1)));
}

fn stat(f: impl FnOnce(&mut Stats)) {
    STATS.with(|s| f(&mut s.borrow_mut()));
}

// ---------------------------------------------------------------------------------------------
// Per-logic reducers (`logic.reducers`)
// ---------------------------------------------------------------------------------------------

/// The mapping of one generated key reducer: `{ [actionTypeOrKey]: (state, payload, meta) => state }`.
struct MappingCore {
    /// Action type or action key id to slot index.
    fns: RefCell<HashMap<u32, u32>>,
    owner: std::rc::Weak<LogicCore>,
}

struct KeyEntry {
    key: JsValue,
    /// Slot index of the key reducer function.
    slot: u32,
    /// Set when the slot holds the reducer that kea generated for this key and the mapping is not
    /// empty. Kea can then skip the call when the action is not in the mapping.
    mapping: Option<Rc<MappingCore>>,
    /// Set when the slot holds kea's reducer for a key without actions: `() => logic.defaults[key]`.
    /// It does not depend on the action, so it does not make the logic opaque. A write to
    /// `logic.defaults` counts as a change to the logic.
    constant: bool,
}

struct Summary {
    types: HashSet<u32>,
    opaque: bool,
}

impl Summary {
    fn may_change(&self, type_id: Option<u32>) -> bool {
        self.opaque || type_id.map_or(false, |t| self.types.contains(&t))
    }
}

struct LogicCore {
    engine_id: u32,
    keys: RefCell<OMap<Rc<KeyEntry>>>,
    /// Mirror of `logic.actionKeys`: action type id to action key id.
    action_keys: RefCell<HashMap<u32, u32>>,
    attached: Rc<Cell<u32>>,
    cache: RefCell<Option<(u32, JsValue)>>,
    summary: RefCell<Option<(u32, Rc<Summary>)>>,
}

impl LogicCore {
    fn changed(&self) {
        *self.cache.borrow_mut() = None;
        *self.summary.borrow_mut() = None;
        if self.attached.get() > 0 {
            bump_epoch();
        }
    }

    fn summary(&self, ep: u32) -> Rc<Summary> {
        if let Some((e, s)) = &*self.summary.borrow() {
            if *e == ep {
                return s.clone();
            }
        }
        let mut types = HashSet::new();
        let mut opaque = false;
        for (_, entry) in self.keys.borrow().iter() {
            match &entry.mapping {
                Some(m) => types.extend(m.fns.borrow().keys().copied()),
                None if entry.constant => {}
                None => opaque = true,
            }
        }
        types.extend(self.action_keys.borrow().keys().copied());
        let s = Rc::new(Summary { types, opaque });
        *self.summary.borrow_mut() = Some((ep, s.clone()));
        s
    }

    fn find_mapped(&self, mapping: &MappingCore, type_id: Option<u32>) -> Option<u32> {
        let t = type_id?;
        let fns = mapping.fns.borrow();
        if let Some(slot) = fns.get(&t) {
            return Some(*slot);
        }
        let key = *self.action_keys.borrow().get(&t)?;
        fns.get(&key).copied()
    }
}

// ---------------------------------------------------------------------------------------------
// Compiled reducer tree
// ---------------------------------------------------------------------------------------------

#[derive(Clone)]
enum Compiled {
    /// A JavaScript reducer function that kea can not see into.
    Opaque(Rc<JsValue>),
    /// The reducer that kea generated for a logic. It combines `logic.reducers`. The second
    /// field is the logic's slot array.
    Logic(Rc<LogicCore>, Rc<JsValue>),
    Combine(Rc<CombineNode>),
    /// A tree node without reducers. It returns its own empty object.
    Empty(Rc<JsValue>),
}

struct Child {
    key: JsValue,
    node: Compiled,
}

struct CombineNode {
    children: Vec<Child>,
    cache: RefCell<Option<(u32, JsValue)>>,
    summary: RefCell<Option<(u32, Rc<Summary>)>>,
}

impl CombineNode {
    fn new(children: Vec<Child>) -> Self {
        CombineNode { children, cache: RefCell::new(None), summary: RefCell::new(None) }
    }

    fn summary(&self, ep: u32) -> Rc<Summary> {
        if let Some((e, s)) = &*self.summary.borrow() {
            if *e == ep {
                return s.clone();
            }
        }
        let mut types = HashSet::new();
        let mut opaque = false;
        for child in &self.children {
            match &child.node {
                Compiled::Opaque(_) => opaque = true,
                Compiled::Empty(_) => {}
                Compiled::Logic(l, _) => {
                    let s = l.summary(ep);
                    opaque |= s.opaque;
                    types.extend(s.types.iter().copied());
                }
                Compiled::Combine(c) => {
                    let s = c.summary(ep);
                    opaque |= s.opaque;
                    types.extend(s.types.iter().copied());
                }
            }
        }
        let s = Rc::new(Summary { types, opaque });
        *self.summary.borrow_mut() = Some((ep, s.clone()));
        s
    }
}

/// One dispatch through the compiled tree.
struct Dispatch<'a> {
    action: &'a JsValue,
    full: JsValue,
    type_id: Option<u32>,
    epoch: u32,
    payload: OnceCell<JsValue>,
    meta: OnceCell<JsValue>,
}

impl<'a> Dispatch<'a> {
    fn payload(&self) -> Result<&JsValue, JsValue> {
        if self.payload.get().is_none() {
            let v = KEY_PAYLOAD.with(|k| js_get(self.action, k))?;
            let _ = self.payload.set(v);
        }
        Ok(self.payload.get().unwrap())
    }

    fn meta(&self) -> Result<&JsValue, JsValue> {
        if self.meta.get().is_none() {
            let v = KEY_META.with(|k| js_get(self.action, k))?;
            let _ = self.meta.set(v);
        }
        Ok(self.meta.get().unwrap())
    }
}

fn type_id_of(action: &JsValue) -> Option<u32> {
    js_type_key(action).and_then(|s| lookup(&s))
}

/// Runs a compiled node. Returns the next state and whether it differs from `state` by `===`.
fn run(node: &Compiled, state: JsValue, d: &Dispatch) -> Result<(JsValue, bool), JsValue> {
    match node {
        Compiled::Opaque(f) => {
            stat(|s| s.js_reducer_calls += 1.0);
            let next = js_call3(f, &state, d.action, &d.full)?;
            let changed = next != state;
            Ok((next, changed))
        }
        Compiled::Empty(obj) => {
            let changed = **obj != state;
            Ok(((**obj).clone(), changed))
        }
        Compiled::Combine(c) => run_combine(c, state, d),
        Compiled::Logic(l, slots) => run_logic(l, slots, state, d),
    }
}

fn cached_same(cache: &RefCell<Option<(u32, JsValue)>>, state: &JsValue, ep: u32) -> bool {
    match &*cache.borrow() {
        Some((e, s)) => *e == ep && s == state,
        None => false,
    }
}

fn check_defined(next: &JsValue, key: &JsValue, d: &Dispatch) -> Result<(), JsValue> {
    if next.is_undefined() {
        Err(js_reducer_undefined_error(key, d.action))
    } else {
        Ok(())
    }
}

fn run_combine(c: &CombineNode, state: JsValue, d: &Dispatch) -> Result<(JsValue, bool), JsValue> {
    if !c.summary(d.epoch).may_change(d.type_id) && cached_same(&c.cache, &state, d.epoch) {
        stat(|s| s.nodes_skipped += 1.0);
        return Ok((state, false));
    }
    stat(|s| s.nodes_run += 1.0);
    let (state, mut changed) = if state.is_undefined() {
        (js_new_obj(), c.children.len() != 0)
    } else {
        let len = js_keys_len(&state)?;
        let changed = len as usize != c.children.len();
        (state, changed)
    };
    let mut results: Vec<JsValue> = Vec::with_capacity(c.children.len());
    for child in &c.children {
        let prev = js_get(&state, &child.key)?;
        let (next, child_changed) = run(&child.node, prev, d)?;
        if let Compiled::Opaque(_) = child.node {
            check_defined(&next, &child.key, d)?;
        }
        changed |= child_changed;
        results.push(next);
    }
    let out = if changed {
        let obj = js_new_obj();
        for (child, value) in c.children.iter().zip(results.iter()) {
            js_set(&obj, &child.key, value)?;
        }
        obj
    } else {
        state
    };
    *c.cache.borrow_mut() = Some((d.epoch, out.clone()));
    Ok((out, changed))
}

fn run_logic(l: &LogicCore, slots: &JsValue, state: JsValue, d: &Dispatch) -> Result<(JsValue, bool), JsValue> {
    if !l.summary(d.epoch).may_change(d.type_id) && cached_same(&l.cache, &state, d.epoch) {
        stat(|s| s.nodes_skipped += 1.0);
        return Ok((state, false));
    }
    stat(|s| s.nodes_run += 1.0);
    // Snapshot the entries so that no borrow is held while JavaScript runs.
    let entries: Vec<Rc<KeyEntry>> = l.keys.borrow().iter().map(|(_, e)| e.clone()).collect();
    let (state, mut changed) = if state.is_undefined() {
        (js_new_obj(), !entries.is_empty())
    } else {
        let len = js_keys_len(&state)?;
        let changed = len as usize != entries.len();
        (state, changed)
    };
    let mut results: Vec<JsValue> = Vec::with_capacity(entries.len());
    for entry in &entries {
        let prev = js_get(&state, &entry.key)?;
        let generated = match &entry.mapping {
            Some(m) if !prev.is_undefined() => Some(m),
            _ => None,
        };
        let next = match generated {
            Some(mapping) => match l.find_mapped(mapping, d.type_id) {
                Some(slot) => {
                    stat(|s| s.js_reducer_calls += 1.0);
                    let next = js_call_slot3(slots, slot, &prev, d.payload()?, d.meta()?)?;
                    check_defined(&next, &entry.key, d)?;
                    changed |= next != prev;
                    next
                }
                None => {
                    stat(|s| s.generated_reducers_skipped += 1.0);
                    prev
                }
            },
            None => {
                stat(|s| s.js_reducer_calls += 1.0);
                let next = js_call_slot3(slots, entry.slot, &prev, d.action, &d.full)?;
                check_defined(&next, &entry.key, d)?;
                changed |= next != prev;
                next
            }
        };
        results.push(next);
    }
    let out = if changed {
        let obj = js_new_obj();
        for (entry, value) in entries.iter().zip(results.iter()) {
            js_set(&obj, &entry.key, value)?;
        }
        obj
    } else {
        state
    };
    *l.cache.borrow_mut() = Some((d.epoch, out.clone()));
    Ok((out, changed))
}

fn reduce_entry(node: &Compiled, state: JsValue, action: &JsValue, full: &JsValue) -> Result<JsValue, JsValue> {
    stat(|s| s.dispatches += 1.0);
    if let Compiled::Opaque(f) = node {
        // A root that is a plain reducer gets the arguments as they are.
        return js_call3(f, &state, action, full);
    }
    // `combineKeaReducers` defaults `state` to `{}` and passes `fullState || state` down. After the
    // first level, `fullState` is always the same truthy value, so it is computed once here.
    let state = match node {
        Compiled::Combine(_) | Compiled::Logic(..) if state.is_undefined() => js_new_obj(),
        _ => state,
    };
    let full = if full.is_truthy() { full.clone() } else { state.clone() };
    let d = Dispatch {
        action,
        full,
        type_id: type_id_of(action),
        epoch: epoch(),
        payload: OnceCell::new(),
        meta: OnceCell::new(),
    };
    Ok(run(node, state, &d)?.0)
}

// ---------------------------------------------------------------------------------------------
// Structural reducer tree (`context.reducers.tree`)
// ---------------------------------------------------------------------------------------------

enum TNode {
    Leaf { func: JsValue, logic: Option<(Rc<LogicCore>, Rc<JsValue>)> },
    Branch(Branch),
}

#[derive(Default)]
struct Branch {
    children: OMap<TNode>,
    /// The compiled form of this branch. A change below this branch clears it.
    memo: Option<Compiled>,
}

fn release(node: &TNode) {
    match node {
        TNode::Leaf { logic: Some((l, _)), .. } => {
            l.attached.set(l.attached.get().saturating_sub(1));
            // The cached state keeps user data alive. A detached logic does not need it.
            *l.cache.borrow_mut() = None;
        }
        TNode::Leaf { .. } => {}
        TNode::Branch(b) => {
            for (_, child) in b.children.iter() {
                release(child);
            }
        }
    }
}

/// Compiles a tree node. Returns the compiled node and whether it contains an empty node.
/// A branch with an empty node is not memoized: kea creates a new empty object for every
/// empty node each time it regenerates a root.
fn compile(node: &mut TNode) -> (Compiled, bool) {
    match node {
        TNode::Leaf { logic: Some((l, slots)), .. } => (Compiled::Logic(l.clone(), slots.clone()), false),
        TNode::Leaf { func, logic: None } => (Compiled::Opaque(Rc::new(func.clone())), false),
        TNode::Branch(b) => {
            if let Some(memo) = &b.memo {
                return (memo.clone(), false);
            }
            let mut children = Vec::with_capacity(b.children.len());
            let mut has_empty = false;
            for (key, child) in b.children.iter_mut() {
                let (compiled, empty) = compile(child);
                has_empty |= empty;
                children.push(Child { key: JsValue::from_str(key), node: compiled });
            }
            if children.is_empty() {
                return (Compiled::Empty(Rc::new(js_new_obj())), true);
            }
            let compiled = Compiled::Combine(Rc::new(CombineNode::new(children)));
            if !has_empty {
                b.memo = Some(compiled.clone());
            }
            (compiled, has_empty)
        }
    }
}

fn materialize(node: &TNode) -> JsValue {
    match node {
        TNode::Leaf { func, .. } => func.clone(),
        TNode::Branch(b) => {
            let obj = js_new_obj();
            for (k, child) in b.children.iter() {
                let _ = js_set(&obj, &JsValue::from_str(k), &materialize(child));
            }
            obj
        }
    }
}

fn import_tree(value: &JsValue) -> Option<TNode> {
    if value.is_function() {
        return Some(TNode::Leaf { func: value.clone(), logic: None });
    }
    if !value.is_object() {
        return None;
    }
    let mut branch = Branch::default();
    let keys = Object::keys(value.unchecked_ref());
    for key in keys.iter() {
        let child = js_get(value, &key).unwrap_or(JsValue::UNDEFINED);
        if let (Some(k), Some(node)) = (key.as_string(), import_tree(&child)) {
            branch.children.insert(k, node);
        }
    }
    Some(TNode::Branch(branch))
}

/// Port of `(pointer && pointer[part]) || undefined` over several parts.
fn node_at<'a>(tree: &'a mut OMap<TNode>, parts: &[String]) -> Option<&'a mut TNode> {
    let (first, rest) = parts.split_first()?;
    let node = tree.get_mut(first)?;
    if rest.is_empty() {
        return Some(node);
    }
    match node {
        TNode::Branch(b) => node_at(&mut b.children, rest),
        TNode::Leaf { .. } => None,
    }
}

fn strings_of(array: &Array) -> Vec<String> {
    array.iter().map(|v| v.as_string().unwrap_or_default()).collect()
}

// ---------------------------------------------------------------------------------------------
// Engine (one per kea context)
// ---------------------------------------------------------------------------------------------

#[derive(Default)]
struct ListenerIndex {
    by_action: HashMap<String, (u64, OMap<Rc<JsValue>>)>,
    by_path: HashMap<String, (u64, JsValue)>,
    seq: u64,
}

#[derive(Default)]
struct EngineState {
    tree: OMap<TNode>,
    roots: OMap<Compiled>,
    redux: OMap<Rc<JsValue>>,
    whitelist: Option<HashSet<String>>,
    combined: Option<Compiled>,
    mount: HashMap<String, (i32, u64)>,
    mount_seq: u64,
    listeners: ListenerIndex,
}

#[wasm_bindgen]
pub struct Engine {
    id: u32,
    st: RefCell<EngineState>,
}

#[wasm_bindgen]
pub struct LogicHandle {
    core: Rc<LogicCore>,
}

#[wasm_bindgen]
pub struct MappingHandle {
    core: Rc<MappingCore>,
}

impl Engine {
    fn regenerate(&self, path_start: &str) {
        let mut guard = self.st.borrow_mut();
        let st = &mut *guard;
        let remove = path_start != "kea"
            && st.whitelist.is_none()
            && matches!(st.tree.get(path_start), Some(TNode::Branch(b)) if b.children.is_empty());
        if remove {
            st.roots.remove(path_start);
        } else {
            let compiled = match st.tree.get_mut(path_start) {
                Some(node) => compile(node).0,
                None => Compiled::Empty(Rc::new(js_new_obj())),
            };
            st.roots.insert(path_start.to_string(), compiled);
        }
        Self::regenerate_combined(st);
    }

    fn regenerate_combined(st: &mut EngineState) {
        let mut merged: OMap<Compiled> = OMap::new();
        for (k, f) in st.redux.iter() {
            merged.insert(k.clone(), Compiled::Opaque(f.clone()));
        }
        for (k, c) in st.roots.iter() {
            merged.insert(k.clone(), c.clone());
        }
        let children = merged
            .iter()
            .map(|(k, c)| Child { key: JsValue::from_str(k), node: c.clone() })
            .collect();
        st.combined = Some(Compiled::Combine(Rc::new(CombineNode::new(children))));
    }

    fn init_root_inner(&self, path_start: &str) -> Result<(), JsValue> {
        {
            let st = self.st.borrow();
            if st.tree.contains_key(path_start) {
                return Ok(());
            }
            if let Some(w) = &st.whitelist {
                if !w.contains(path_start) {
                    return Err(js_whitelist_error(path_start));
                }
            }
        }
        self.st.borrow_mut().tree.insert(path_start.to_string(), TNode::Branch(Branch::default()));
        self.regenerate(path_start);
        Ok(())
    }

    fn attach_inner(&self, path: Vec<String>, func: JsValue, logic: Option<(Rc<LogicCore>, Rc<JsValue>)>) -> Result<JsValue, JsValue> {
        let path_start = path[0].clone();
        self.init_root_inner(&path_start)?;
        {
            let mut guard = self.st.borrow_mut();
            let mut pointer: &mut OMap<TNode> = &mut guard.tree;
            for (i, part) in path.iter().enumerate() {
                if i == path.len() - 1 {
                    let blocked = match pointer.get(part) {
                        None => false,
                        Some(TNode::Branch(b)) if i == 0 && b.children.is_empty() => false,
                        Some(TNode::Leaf { .. }) => false,
                        Some(other) => {
                            return Ok(materialize(other));
                        }
                    };
                    debug_assert!(!blocked);
                    if let Some((l, _)) = &logic {
                        l.attached.set(l.attached.get() + 1);
                        *l.cache.borrow_mut() = None;
                    }
                    if let Some(old) = pointer.insert(part.clone(), TNode::Leaf { func, logic }) {
                        release(&old);
                    }
                    break;
                }
                if !pointer.contains_key(part) {
                    pointer.insert(part.clone(), TNode::Branch(Branch::default()));
                }
                match pointer.get_mut(part) {
                    Some(TNode::Branch(b)) => {
                        b.memo = None;
                        pointer = &mut b.children;
                    }
                    Some(leaf) => return Ok(materialize(leaf)),
                    None => unreachable!(),
                }
            }
        }
        self.regenerate(&path_start);
        Ok(JsValue::TRUE)
    }
}

#[wasm_bindgen]
impl Engine {
    #[wasm_bindgen(constructor)]
    pub fn new() -> Engine {
        let id = NEXT_ENGINE_ID.with(|n| {
            let id = n.get();
            n.set(id + 1);
            id
        });
        Engine { id, st: RefCell::new(EngineState::default()) }
    }

    #[wasm_bindgen(js_name = createLogic)]
    pub fn create_logic(&self) -> LogicHandle {
        LogicHandle {
            core: Rc::new(LogicCore {
                engine_id: self.id,
                keys: RefCell::new(OMap::new()),
                action_keys: RefCell::new(HashMap::new()),
                attached: Rc::new(Cell::new(0)),
                cache: RefCell::new(None),
                summary: RefCell::new(None),
            }),
        }
    }

    // --- reducer tree -------------------------------------------------------------------------

    #[wasm_bindgen(js_name = initRoot)]
    pub fn init_root(&self, path_start: &str) -> Result<(), JsValue> {
        self.init_root_inner(path_start)
    }

    /// Attaches an opaque reducer function. Returns `true`, or the value that blocks the path.
    pub fn attach(&self, path: Array, func: JsValue) -> Result<JsValue, JsValue> {
        self.attach_inner(strings_of(&path), func, None)
    }

    /// Attaches the reducer that kea generated for a logic. Returns `true`, or the value that
    /// blocks the path.
    #[wasm_bindgen(js_name = attachLogic)]
    pub fn attach_logic(&self, path: Array, func: JsValue, logic: &LogicHandle, slots: JsValue) -> Result<JsValue, JsValue> {
        let core = if logic.core.engine_id == self.id { Some((logic.core.clone(), Rc::new(slots))) } else { None };
        self.attach_inner(strings_of(&path), func, core)
    }

    /// Port of `detachReducer` without the strategy handling. Returns `detached`.
    pub fn detach(&self, path: Array) -> bool {
        let path = strings_of(&path);
        let path_start = path[0].clone();
        let mut detached = false;
        {
            let mut guard = self.st.borrow_mut();
            if path.len() >= 2 {
                let mut i = path.len() as isize - 2;
                while i >= 0 {
                    let iu = i as usize;
                    let node = node_at(&mut guard.tree, &path[..=iu]);
                    if let Some(TNode::Branch(b)) = node {
                        let next_part = &path[iu + 1];
                        if b.children.is_empty() {
                            // next
                        } else if iu == path.len() - 2 && matches!(b.children.get(next_part), Some(TNode::Leaf { .. })) {
                            if let Some(old) = b.children.remove(next_part) {
                                release(&old);
                            }
                            b.memo = None;
                            detached = true;
                        } else if detached
                            && iu < path.len() - 2
                            && matches!(b.children.get(next_part), Some(TNode::Branch(c)) if c.children.is_empty())
                        {
                            b.children.remove(next_part);
                            b.memo = None;
                        } else {
                            break;
                        }
                    }
                    i -= 1;
                }
                // Memos of the ancestors of a removed node are stale.
                if detached {
                    let mut pointer: Option<&mut OMap<TNode>> = Some(&mut guard.tree);
                    for part in &path[..path.len() - 1] {
                        match pointer.take().and_then(|m| m.get_mut(part)) {
                            Some(TNode::Branch(b)) => {
                                b.memo = None;
                                pointer = Some(&mut b.children);
                            }
                            _ => break,
                        }
                    }
                }
            }
        }
        self.regenerate(&path_start);
        detached
    }

    /// Runs `context.reducers.combined`.
    #[wasm_bindgen(js_name = reduceCombined)]
    pub fn reduce_combined(&self, state: JsValue, action: &JsValue, full: &JsValue) -> Result<JsValue, JsValue> {
        let node = self.st.borrow().combined.clone();
        match node {
            Some(node) => reduce_entry(&node, state, action, full),
            None => Ok(JsValue::UNDEFINED),
        }
    }

    /// Runs `context.reducers.roots[pathStart]`, or returns `state` if the root does not exist.
    #[wasm_bindgen(js_name = reduceRoot)]
    pub fn reduce_root(&self, path_start: &str, state: JsValue, action: &JsValue, full: &JsValue) -> Result<JsValue, JsValue> {
        let node = self.st.borrow().roots.get(path_start).cloned();
        match node {
            Some(node) => reduce_entry(&node, state, action, full),
            None => Ok(state),
        }
    }

    #[wasm_bindgen(js_name = regenerateRoot)]
    pub fn regenerate_root(&self, path_start: &str) {
        self.regenerate(path_start);
    }

    #[wasm_bindgen(js_name = hasRoot)]
    pub fn has_root(&self, path_start: &str) -> bool {
        self.st.borrow().roots.contains_key(path_start)
    }

    #[wasm_bindgen(js_name = rootKeys)]
    pub fn root_keys(&self) -> Array {
        self.st.borrow().roots.iter().map(|(k, _)| JsValue::from_str(k)).collect()
    }

    #[wasm_bindgen(js_name = hasCombined)]
    pub fn has_combined(&self) -> bool {
        self.st.borrow().combined.is_some()
    }

    #[wasm_bindgen(js_name = regenerateCombined)]
    pub fn regenerate_combined_js(&self) {
        Self::regenerate_combined(&mut self.st.borrow_mut());
    }

    #[wasm_bindgen(js_name = setRedux)]
    pub fn set_redux(&self, keys: Array, values: Array) {
        let mut st = self.st.borrow_mut();
        st.redux = OMap::new();
        for (k, v) in keys.iter().zip(values.iter()) {
            if let Some(k) = k.as_string() {
                st.redux.insert(k, Rc::new(v));
            }
        }
    }

    #[wasm_bindgen(js_name = getRedux)]
    pub fn get_redux(&self) -> JsValue {
        let obj = js_new_obj();
        for (k, v) in self.st.borrow().redux.iter() {
            let _ = js_set(&obj, &JsValue::from_str(k), v);
        }
        obj
    }

    #[wasm_bindgen(js_name = setWhitelist)]
    pub fn set_whitelist(&self, keys: Option<Array>) {
        self.st.borrow_mut().whitelist = keys.map(|a| strings_of(&a).into_iter().collect());
    }

    #[wasm_bindgen(js_name = getWhitelist)]
    pub fn get_whitelist(&self) -> JsValue {
        match &self.st.borrow().whitelist {
            None => JsValue::FALSE,
            Some(w) => {
                let obj = js_new_obj();
                for k in w {
                    let _ = js_set(&obj, &JsValue::from_str(k), &JsValue::TRUE);
                }
                obj
            }
        }
    }

    #[wasm_bindgen(js_name = getTree)]
    pub fn get_tree(&self) -> JsValue {
        let obj = js_new_obj();
        for (k, node) in self.st.borrow().tree.iter() {
            let _ = js_set(&obj, &JsValue::from_str(k), &materialize(node));
        }
        obj
    }

    #[wasm_bindgen(js_name = setTree)]
    pub fn set_tree(&self, value: JsValue) {
        let mut st = self.st.borrow_mut();
        for (_, old) in st.tree.drain() {
            release(&old);
        }
        if let Some(TNode::Branch(b)) = import_tree(&value) {
            st.tree = b.children;
        }
    }

    // --- mount counters -----------------------------------------------------------------------

    /// `counter[path] += count`. Returns true if the counter now equals `count`.
    #[wasm_bindgen(js_name = mountIncrement)]
    pub fn mount_increment(&self, path: &str, count: i32) -> bool {
        let mut guard = self.st.borrow_mut();
        let st = &mut *guard;
        st.mount_seq += 1;
        let seq = st.mount_seq;
        let entry = st.mount.entry(path.to_string()).or_insert((0, seq));
        entry.0 += count;
        entry.0 == count
    }

    /// `counter[path] -= 1`. Returns true if the counter is now zero.
    #[wasm_bindgen(js_name = mountDecrement)]
    pub fn mount_decrement(&self, path: &str) -> bool {
        let mut guard = self.st.borrow_mut();
        let st = &mut *guard;
        st.mount_seq += 1;
        let seq = st.mount_seq;
        let entry = st.mount.entry(path.to_string()).or_insert((0, seq));
        entry.0 -= 1;
        entry.0 == 0
    }

    #[wasm_bindgen(js_name = mountDelete)]
    pub fn mount_delete(&self, path: &str) {
        self.st.borrow_mut().mount.remove(path);
    }

    #[wasm_bindgen(js_name = mountCount)]
    pub fn mount_count(&self, path: &str) -> Option<i32> {
        self.st.borrow().mount.get(path).map(|e| e.0)
    }

    #[wasm_bindgen(js_name = mountCounterObject)]
    pub fn mount_counter_object(&self) -> JsValue {
        let st = self.st.borrow();
        let mut entries: Vec<(&String, &(i32, u64))> = st.mount.iter().collect();
        entries.sort_by_key(|(_, (_, seq))| *seq);
        let obj = js_new_obj();
        for (k, (count, _)) in entries {
            let _ = js_set(&obj, &JsValue::from_str(k), &JsValue::from(*count));
        }
        obj
    }

    // --- listener index -----------------------------------------------------------------------

    /// `byPath[path] = listeners`, and `byAction[types[i]][path] = arrays[i]`.
    #[wasm_bindgen(js_name = listenersAdd)]
    pub fn listeners_add(&self, path: &str, listeners: JsValue, types: Array, arrays: Array) {
        let mut guard = self.st.borrow_mut();
        let idx = &mut guard.listeners;
        idx.seq += 1;
        let seq = idx.seq;
        match idx.by_path.get_mut(path) {
            Some(slot) => slot.1 = listeners,
            None => {
                idx.by_path.insert(path.to_string(), (seq, listeners));
            }
        }
        for (t, arr) in types.iter().zip(arrays.iter()) {
            let t = t.as_string().unwrap_or_default();
            idx.seq += 1;
            let seq = idx.seq;
            let slot = idx.by_action.entry(t).or_insert_with(|| (seq, OMap::new()));
            slot.1.insert(path.to_string(), Rc::new(arr));
        }
    }

    #[wasm_bindgen(js_name = listenersRemove)]
    pub fn listeners_remove(&self, path: &str, types: Array) {
        let mut guard = self.st.borrow_mut();
        let idx = &mut guard.listeners;
        for t in strings_of(&types) {
            let empty = match idx.by_action.get_mut(&t) {
                Some(slot) => {
                    slot.1.remove(path);
                    slot.1.is_empty()
                }
                None => false,
            };
            if empty {
                idx.by_action.remove(&t);
            }
        }
        idx.by_path.remove(path);
    }

    /// The listener arrays for `action.type`, in kea's order, or `undefined`. The middleware calls
    /// them in JavaScript.
    #[wasm_bindgen(js_name = listenersFor)]
    pub fn listeners_for(&self, action: &JsValue) -> JsValue {
        let Some(t) = js_type_key(action) else { return JsValue::UNDEFINED };
        let arrays: Vec<Rc<JsValue>> = {
            let st = self.st.borrow();
            match st.listeners.by_action.get(&t) {
                Some((_, m)) => m.iter().map(|(_, a)| a.clone()).collect(),
                None => return JsValue::UNDEFINED,
            }
        };
        arrays.iter().map(|a| (**a).clone()).collect::<Array>().into()
    }

    #[wasm_bindgen(js_name = listenersByAction)]
    pub fn listeners_by_action(&self) -> JsValue {
        let st = self.st.borrow();
        let mut types: Vec<(&String, &(u64, OMap<Rc<JsValue>>))> = st.listeners.by_action.iter().collect();
        types.sort_by_key(|(_, (seq, _))| *seq);
        let mut sorted: OMap<JsValue> = OMap::new();
        for (t, (_, m)) in types {
            let inner = js_new_obj();
            for (p, a) in m.iter() {
                let _ = js_set(&inner, &JsValue::from_str(p), a);
            }
            sorted.insert(t.clone(), inner);
        }
        let obj = js_new_obj();
        for (t, inner) in sorted.iter() {
            let _ = js_set(&obj, &JsValue::from_str(t), inner);
        }
        obj
    }

    #[wasm_bindgen(js_name = listenersByPath)]
    pub fn listeners_by_path(&self) -> JsValue {
        let st = self.st.borrow();
        let mut paths: Vec<(&String, &(u64, JsValue))> = st.listeners.by_path.iter().collect();
        paths.sort_by_key(|(_, (seq, _))| *seq);
        let mut sorted: OMap<JsValue> = OMap::new();
        for (p, (_, v)) in paths {
            sorted.insert(p.clone(), v.clone());
        }
        let obj = js_new_obj();
        for (p, v) in sorted.iter() {
            let _ = js_set(&obj, &JsValue::from_str(p), v);
        }
        obj
    }
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

#[wasm_bindgen]
impl LogicHandle {
    /// Runs `combineKeaReducers(logic.reducers)(state, action, fullState)`.
    pub fn reduce(&self, slots: JsValue, state: JsValue, action: &JsValue, full: &JsValue) -> Result<JsValue, JsValue> {
        reduce_entry(&Compiled::Logic(self.core.clone(), Rc::new(slots)), state, action, full)
    }

    /// `logic.reducers[key] = slots[slot]`, for a function that kea did not generate.
    #[wasm_bindgen(js_name = setKey)]
    pub fn set_key(&self, key: &str, slot: u32) {
        let entry = KeyEntry { key: JsValue::from_str(key), slot, mapping: None, constant: false };
        self.core.keys.borrow_mut().insert(key.to_string(), Rc::new(entry));
        self.core.changed();
    }

    /// `logic.reducers[key] = slots[slot]`, for the reducer that kea generated from `mapping`.
    #[wasm_bindgen(js_name = setGeneratedKey)]
    pub fn set_generated_key(&self, key: &str, slot: u32, mapping: &MappingHandle) {
        let entry = KeyEntry { key: JsValue::from_str(key), slot, mapping: Some(mapping.core.clone()), constant: false };
        self.core.keys.borrow_mut().insert(key.to_string(), Rc::new(entry));
        self.core.changed();
    }

    /// `logic.reducers[key] = () => logic.defaults[key]`, the reducer kea generates without actions.
    #[wasm_bindgen(js_name = setConstantKey)]
    pub fn set_constant_key(&self, key: &str, slot: u32) {
        let entry = KeyEntry { key: JsValue::from_str(key), slot, mapping: None, constant: true };
        self.core.keys.borrow_mut().insert(key.to_string(), Rc::new(entry));
        self.core.changed();
    }

    /// Reports a change that the engine can not see, such as a write to `logic.defaults`.
    pub fn touch(&self) {
        self.core.changed();
    }

    #[wasm_bindgen(js_name = deleteKey)]
    pub fn delete_key(&self, key: &str) {
        self.core.keys.borrow_mut().remove(key);
        self.core.changed();
    }

    #[wasm_bindgen(js_name = clearKeys)]
    pub fn clear_keys(&self) {
        *self.core.keys.borrow_mut() = OMap::new();
        self.core.changed();
    }

    /// `logic.actionKeys[type] = key`. A falsy key removes the entry.
    #[wasm_bindgen(js_name = setActionKey)]
    pub fn set_action_key(&self, action_type: &str, key: Option<String>) {
        let t = intern(action_type);
        match key {
            Some(k) if !k.is_empty() => {
                let k = intern(&k);
                self.core.action_keys.borrow_mut().insert(t, k);
            }
            _ => {
                self.core.action_keys.borrow_mut().remove(&t);
            }
        }
        self.core.changed();
    }

    #[wasm_bindgen(js_name = clearActionKeys)]
    pub fn clear_action_keys(&self) {
        self.core.action_keys.borrow_mut().clear();
        self.core.changed();
    }

    #[wasm_bindgen(js_name = createMapping)]
    pub fn create_mapping(&self) -> MappingHandle {
        MappingHandle {
            core: Rc::new(MappingCore { fns: RefCell::new(HashMap::new()), owner: Rc::downgrade(&self.core) }),
        }
    }
}

#[wasm_bindgen]
impl MappingHandle {
    /// `mapping[key] = slots[slot]`. Kea only calls truthy entries. Pass `undefined` for a falsy
    /// value, which removes the entry.
    pub fn set(&self, key: &str, slot: Option<u32>) {
        let k = intern(key);
        if let Some(slot) = slot {
            self.core.fns.borrow_mut().insert(k, slot);
        } else {
            self.core.fns.borrow_mut().remove(&k);
        }
        if let Some(owner) = self.core.owner.upgrade() {
            owner.changed();
        }
    }
}

/// Port of `createActionType`: `setDuckId` + `scenes.ducks` -> `set duck id (scenes.ducks)`.
#[wasm_bindgen(js_name = createActionType)]
pub fn create_action_type(key: &str, path_string: &str) -> String {
    format!("{} ({})", to_spaces(key), path_string)
}

/// Port of `key.replace(/(?:^|\.?)([A-Z])/g, (x, y) => ' ' + y.toLowerCase()).replace(/^ /, '')`.
fn to_spaces(key: &str) -> String {
    let chars: Vec<char> = key.chars().collect();
    let mut out = String::with_capacity(key.len() + 4);
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '.' && i + 1 < chars.len() && chars[i + 1].is_ascii_uppercase() {
            // The dot is part of the match and is replaced together with the letter.
            i += 1;
            continue;
        }
        if c.is_ascii_uppercase() {
            out.push(' ');
            out.push(c.to_ascii_lowercase());
        } else {
            out.push(c);
        }
        i += 1;
    }
    match out.strip_prefix(' ') {
        Some(rest) => rest.to_string(),
        None => out,
    }
}

/// Registers an action type so that dispatch can find it. Listener and reducer keys call this.
#[wasm_bindgen(js_name = internType)]
pub fn intern_type(action_type: &str) -> u32 {
    intern(action_type)
}

/// Counters for benchmarks: dispatches, skipped and run nodes, and JavaScript reducer calls.
#[wasm_bindgen(js_name = engineStats)]
pub fn engine_stats() -> JsValue {
    STATS.with(|s| {
        let s = s.borrow();
        let obj = js_new_obj();
        let set = |k: &str, v: f64| {
            let _ = js_set(&obj, &JsValue::from_str(k), &JsValue::from_f64(v));
        };
        set("dispatches", s.dispatches);
        set("nodesSkipped", s.nodes_skipped);
        set("nodesRun", s.nodes_run);
        set("jsReducerCalls", s.js_reducer_calls);
        set("generatedReducersSkipped", s.generated_reducers_skipped);
        obj
    })
}

#[wasm_bindgen(js_name = resetEngineStats)]
pub fn reset_engine_stats() {
    STATS.with(|s| *s.borrow_mut() = Stats::default());
}

#[cfg(test)]
mod tests {
    use super::to_spaces;

    #[test]
    fn to_spaces_matches_the_kea_regex() {
        assert_eq!(to_spaces("setDuckId"), "set duck id");
        assert_eq!(to_spaces("SetDuck"), "set duck");
        assert_eq!(to_spaces("a.B"), "a b");
        assert_eq!(to_spaces("..A"), ". a");
        assert_eq!(to_spaces("loadURLs"), "load u r ls");
        assert_eq!(to_spaces("plain"), "plain");
        assert_eq!(to_spaces("ünïcode"), "ünïcode");
    }
}
