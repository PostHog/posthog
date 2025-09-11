use std::{any::Any, collections::HashMap};

use serde::de::DeserializeOwned;
use serde_json::Value as JsonValue;

use crate::{
    context::{ExecutionContext, Symbol},
    error::VmError,
    memory::{HeapReference, VmHeap},
    ops::Operation,
    util::{get_json_nested, like, regex_match},
    values::{Callable, Closure, FromHogLiteral, HogLiteral, HogValue, LocalCallable, Num, NumOp},
};

pub const MAX_JSON_SERDE_DEPTH: usize = 64;

/// The outcome of a virtual machine step.
#[derive(Debug, Clone)]
pub enum StepOutcome {
    /// The program has completed, returning a value
    Finished(JsonValue),
    /// The program has requested a native function call
    NativeCall(String, Vec<HogValue>),
    /// The program has requested another step
    Continue,
}

/// Some debug information about a virtual machine failure, returned by some
/// helpers when a VM step returns an error
#[derive(Debug, Clone)]
pub struct VmFailure {
    pub error: VmError,
    pub ip: usize,
    pub stack: Vec<HogValue>, // TODO - only used for debugging, should remove
    pub step: usize,
}

/// The Hog Virtual Machine. Represents the state of a running program.
pub struct HogVM<'a> {
    /// The heap of the virtual machine. Generally used for `HogValue::deref`, to allow you to access
    /// `HogLiteral` values for native function implementation.
    pub heap: VmHeap, // Needs to be pub to allow users to write their own extension native functions
    stack: Vec<HogValue>,

    stack_frames: Vec<CallFrame>,
    throw_frames: Vec<ThrowFrame>,
    ip: usize,

    context: &'a ExecutionContext,
    // The base program is None, but calling into e.g. hog standard library functions involves changing the "module"
    // the pointer is currently pointing into to e.g. "arrayExists", as part of the function call that branches into
    // that function.
    current_symbol: Option<Symbol>,
}

struct CallFrame {
    ret_ptr: usize,               // Where to jump back to when we're done
    ret_symbol: Option<Symbol>,   // The module to return to when we're done
    stack_start: usize,           // Point in the stack the frame values start
    captures: Vec<HeapReference>, // Values captured from the parent scope/frame
}

struct ThrowFrame {
    catch_ptr: usize,             // The ptr to jump to if we throw
    catch_symbol: Option<Symbol>, // The module to return to if we throw
    stack_start: usize,           // The stack size when we entered the try
    call_depth: usize,            // The depth of the call stack when we entered the try
}

impl<'a> HogVM<'a> {
    pub fn new(context: &'a ExecutionContext) -> Result<Self, VmError> {
        Ok(Self {
            stack: Vec::new(),
            stack_frames: Vec::new(),
            throw_frames: Vec::new(),
            ip: 0,
            current_symbol: None,
            context,
            heap: VmHeap::new(context.max_heap_size),
        })
    }

    /// Step the virtual machine, writing some debug information to the provided output function.
    pub fn debug_step(&mut self, output: &dyn Fn(String)) -> Result<StepOutcome, VmError> {
        let op: Operation = self.next()?;
        let mut surrounding = Vec::new();
        let start = self.ip.saturating_sub(2);
        for i in 0..5 {
            if let Ok(op) = self.context.get_bytecode(start + i, &self.current_symbol) {
                surrounding.push(op);
            }
        }

        self.ip -= 1;
        output(format!(
            "Op ({}), module {:?}: {:?} [{:?}], Stack: {:?}",
            self.ip, self.current_symbol, op, surrounding, self.stack
        ));
        self.step()
    }

    /// Step the virtual machine one cycle.
    pub fn step(&mut self) -> Result<StepOutcome, VmError> {
        let op: Operation = self.next()?;

        match op {
            Operation::GetGlobal => {
                // GetGlobal is used to do 1 of 2 things, either push a value from a global variable onto the stack, or push a new
                // function reference (referred to in other impls as a "closure") onto the stack - either a native one, or a hog one
                let mut chain = Vec::new();
                let count: usize = self.next()?;
                for _ in 0..count {
                    chain.push(self.pop_stack()?);
                }
                if chain.is_empty() {
                    return Err(VmError::UnknownGlobal("".to_string()));
                }

                if let Some(found) = get_json_nested(&self.context.globals, &chain, self)? {
                    let val = self.json_to_hog(found)?;
                    self.push_stack(val)?;
                } else if let Ok(closure) = self.get_fn_reference(&chain) {
                    self.push_stack(closure)?;
                } else if get_json_nested(&self.context.globals, &chain[..1], self)?.is_some() {
                    // If the first element of the chain is a global, push null onto the stack, e.g.
                    // if a program is looking for "properties.blah", and "properties" exists, but
                    // "blah" doesn't, push null onto the stack.
                    self.push_stack(HogLiteral::Null)?;
                } else {
                    // But if the first element in the chain didn't exist, this is an error (the mental model here
                    // comes from SQL, where a missing column is an error, but a missing field in a column is, or
                    // at least can be, treated as a null value).
                    return Err(VmError::UnknownGlobal(format!("{chain:?}")));
                }
            }
            // We don't implement DeclareFn, because it's not used in the current compiler - it uses
            // "callables" constructed on the stack, which are then called by constructing a "closure",
            // which is basically a function call that wraps a "callable" and populates it's argument list
            Operation::DeclareFn => return Err(VmError::NotImplemented("DeclareFn".to_string())),
            Operation::CallGlobal => {
                // The TS impl here has a bunch of special case handling for functions with particular names.
                // I'm hoping I can simplify that here by unifying the native call interface a bit
                let name: String = self.next()?;
                let arg_count: usize = self.next()?;
                // NOTE - the TS implementation has a clause here that looks for the name in the
                // "declared functions" - basically, the legacy way of declaring a function before Callable
                // and closures were introduced. We leave it out because, as above, DeclareFn isn't supported
                let available_args = self.stack.len() - self.current_frame_base();
                if available_args < arg_count {
                    return Err(VmError::NotEnoughArguments(name, available_args, arg_count));
                }
                let symbol = Symbol::new("stl", &name);
                if self.context.has_symbol(&symbol) {
                    // Cross module calls are done in a manner very similar to CallLocal, just with some
                    // messing around with the current state module.
                    return self.prep_cross_module_call(symbol, arg_count);
                }

                let mut args = Vec::with_capacity(arg_count);
                for _ in 0..arg_count {
                    args.push(self.pop_stack()?);
                }
                if self.context.version() != 0 {
                    // In v0, the arguments were expected to be passed in
                    // stack pop order, not push order. We simulate that here
                    // but always popping, but then maybe reversing
                    args.reverse();
                }
                // This VM does native calls like so: it returns a "native call" struct,
                // which the executing environment can use to execute the native call.
                return Ok(self.prep_native_call(name, args));
            }
            Operation::And => {
                let count: usize = self.next()?;
                let mut acc: HogLiteral = true.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    let value = value.deref(&self.heap)?;
                    acc = acc.and(value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Or => {
                let count: usize = self.next()?;
                let mut acc: HogLiteral = false.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    let value = value.deref(&self.heap)?;
                    acc = acc.or(value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Not => {
                let val = self.pop_stack_as::<bool>()?;
                // TODO - technically, we could assert here that this push will always succeed,
                // and it'd let us skip a bounds check I /think/, but lets not go microoptimizing yet
                self.push_stack(HogLiteral::from(!val))?;
            }
            Operation::Plus => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Add, &a, &b)?)?;
            }
            Operation::Minus => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Sub, &a, &b)?)?;
            }
            Operation::Mult => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Mul, &a, &b)?)?;
            }
            Operation::Div => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Div, &a, &b)?)?;
            }
            Operation::Mod => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Mod, &a, &b)?)?;
            }
            Operation::Eq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.equals(&b, &self.heap)?)?;
            }
            Operation::NotEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.not_equals(&b, &self.heap)?)?;
            }
            Operation::Gt => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Gt, &a, &b)?)?;
            }
            Operation::GtEq => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Gte, &a, &b)?)?;
            }
            Operation::Lt => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Lt, &a, &b)?)?;
            }
            Operation::LtEq => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Lte, &a, &b)?)?;
            }
            Operation::Like => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(like(val, pat, true)?)?;
            }
            Operation::Ilike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(like(val, pat, false)?)?;
            }
            Operation::NotLike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!like(val, pat, true)?)?;
            }
            Operation::NotIlike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!like(val, pat, false)?)?;
            }
            Operation::In => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle, &self.heap)?)?;
            }
            Operation::NotIn => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle, &self.heap)?.not()?)?;
            }
            Operation::Regex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(regex_match(val, pat, true)?)?;
            }
            Operation::NotRegex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!regex_match(val, pat, true)?)?;
            }
            Operation::Iregex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(regex_match(val, pat, false)?)?;
            }
            Operation::NotIregex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!regex_match(val, pat, false)?)?;
            }
            Operation::InCohort => return Err(VmError::NotImplemented("InCohort".to_string())),
            Operation::NotInCohort => {
                return Err(VmError::NotImplemented("NotInCohort".to_string()))
            }
            Operation::True => {
                self.push_stack(true)?;
            }
            Operation::False => {
                self.push_stack(false)?;
            }
            Operation::Null => {
                self.push_stack(HogLiteral::Null)?;
            }
            Operation::String => {
                let val: String = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Integer => {
                let val: i64 = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Float => {
                let val: f64 = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Pop => {
                self.pop_stack()?;
            }
            Operation::GetLocal => {
                let base = self.current_frame_base();
                // Usize as a positive offset from the current frame
                let offset: usize = self.next()?;
                let ptr = self.hoist(base.checked_add(offset).ok_or(VmError::IntegerOverflow)?)?;
                self.push_stack(ptr)?;
            }
            Operation::SetLocal => {
                // Replace some item "lower" in the stack with the top one.
                let base = self.current_frame_base();
                // Usize as a positive offset from the current frame
                let offset: usize = self.next()?;
                let value = self.pop_stack()?;
                self.set_stack_val(
                    base.checked_add(offset).ok_or(VmError::IntegerOverflow)?,
                    value,
                )?;
            }
            Operation::Return => {
                let result = self.pop_stack()?;
                let last_frame = self.stack_frames.pop();
                let Some(frame) = last_frame else {
                    return Ok(StepOutcome::Finished(self.hog_to_json(&result)?));
                };

                // NOTE - this diverges from the TS impl
                // if self.stack_frames.is_empty() {
                //     return Ok(StepOutcome::Finished(result.deref(&self.heap)?.clone()));
                // };
                //
                self.current_symbol = frame.ret_symbol;
                self.truncate_stack(frame.stack_start)?;
                self.ip = frame.ret_ptr;
                self.push_stack(result)?;
            }
            Operation::Jump => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                self.ip = ((self.ip as i64)
                    .checked_add(offset as i64)
                    .ok_or(VmError::IntegerOverflow)?) as usize;
            }
            Operation::JumpIfFalse => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                if !self.pop_stack_as::<bool>()? {
                    self.ip = ((self.ip as i64)
                        .checked_add(offset as i64)
                        .ok_or(VmError::IntegerOverflow)?) as usize;
                }
            }
            Operation::JumpIfStackNotNull => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                // Weirdly, this operation doesn't pop the value from the stack. This is mostly a random choice.
                if !self.stack.is_empty() {
                    let item = self.clone_stack_item(self.stack.len() - 1)?;
                    let item = item.deref(&self.heap)?;
                    if !matches!(item, HogLiteral::Null) {
                        self.ip = ((self.ip as i64)
                            .checked_add(offset as i64)
                            .ok_or(VmError::IntegerOverflow)?)
                            as usize;
                    }
                }
            }
            Operation::Dict => {
                let element_count: usize = self.next()?;
                let mut keys = Vec::with_capacity(element_count);
                let mut values = Vec::with_capacity(element_count);
                // The keys and values are pushed into the stack in key:value, key:value pairs, but we're
                // going to walk the stack backwards to construct the dictionary
                for _ in 0..element_count {
                    // Note we don't put references into collections ever
                    values.push(self.pop_stack()?);
                    keys.push(self.pop_stack_as::<String>()?);
                }
                let map: HashMap<String, HogValue> =
                    HashMap::from_iter(keys.into_iter().zip(values));
                let obj = HogLiteral::Object(map);
                // For the non-primitive types below (objects, arrays, "tuples"), we /always/ heap allocate them. The reason
                // is that the pattern for e.g. nestedly setting an array value is to GetLocal followed by GetProperty, followed
                // by a SetProperty. If the array is "flat", as in, element 3 is a HogLiteral rather than Value, that SetProperty
                // will do nothing, because there's nowhere to write the new value /to/ (as the stack copy of the literal array would be
                // immediately dropped). We assert in SetProperty that the target is a reference, in order to prevent this surprising no-op
                // behaviour, but that means we have to either always heap-allocate our indexable values, or hoist in GetProperty. I've decided
                // to pay the cost of heap-allocating them up-front (and therefore chasing an extra pointer), because I think it more closely
                // mirrors the semantics of e.g. JavaScript or Python, which is what hog is based around.
                let ptr = self.heap.emplace(obj)?;
                self.push_stack(ptr)?;
            }
            Operation::Array => {
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the array to be in pushed order
                elements.reverse();
                let array = HogLiteral::Array(elements);
                // See above
                let ptr = self.heap.emplace(array)?;
                self.push_stack(ptr)?;
            }
            Operation::Tuple => {
                // The compiler has special case handling for tuples, but the typescript VM doesn't, so neither do we,
                // this is effectively Array
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the "tuple" to be in pushed order
                elements.reverse();
                let tuple = HogLiteral::Array(elements);
                // See above
                let ptr = self.heap.emplace(tuple)?;
                self.push_stack(ptr)?;
            }
            Operation::GetProperty => {
                let needle = self.pop_stack()?;
                let haystack = self.pop_stack()?;
                let chain = [needle];
                let Some(res) = haystack.get_nested(&chain, &self.heap)? else {
                    return Err(VmError::UnknownProperty(format!("{:?}", chain[0])));
                };
                self.push_stack(res.clone())?;
            }
            Operation::GetPropertyNullish => {
                let needle = self.pop_stack()?;
                let haystack = self.pop_stack()?;
                let chain = [needle];
                let res = haystack
                    .get_nested(&chain, &self.heap)?
                    .cloned()
                    .unwrap_or(HogLiteral::Null.into());
                self.push_stack(res)?;
            }
            Operation::SetProperty => {
                // Set property is a little tricky, because it assumes the object whose property is being set is
                // a reference. We assert this here - basically, we don't allow SET_PROPERTY to be a no-op, unlike the
                // original implementation, which would allow SET_PROPERTY to be done even if the target was dropped immediately
                // after the operation
                // Value to set - this could be a literal or a reference
                let val = self.pop_stack()?;

                // Location to set it at in the target - this could be a literal or a reference, but
                // it doesn't matter which it is, we deref anyway as only literals can be object keys
                let key: HogLiteral = self.pop_stack_as()?;

                // This can be either a literal or a reference. If it's a reference, we have to deref_mut it
                // from the head, so we can modify it
                let mut target = self.pop_stack()?;
                let target = match &mut target {
                    HogValue::Ref(ptr) => self.heap.get_mut(*ptr)?,
                    HogValue::Lit(_) => {
                        // TODO - this is a divergence from the original implementation - basically, if the target you've specified isn't on the heap,
                        // we'll drop it immediately after setting the property, which is a no-op. This should never happen - we should be using GET_LOCAL
                        // to hoist properties onto the heap before calling SET_PROPERTY, I /think/, but I'm not certain. I might end up making all
                        // objects be auto-allocated on the heap, just to be certain we're never hit this case for anything set_property() would succeed for
                        return Err(VmError::ExpectedObject);
                    }
                };

                let mut allocated_bytes = val.size();
                let key_bytes = key.size();
                let freed_bytes = target.set_property(key, val)?;
                if freed_bytes == 0 {
                    allocated_bytes += key_bytes; // We inserted a new key as well as a new prop
                }

                // This doesn't assert the allocation is possible - the next one will fail, which is good enough
                self.heap.current_bytes = self
                    .heap
                    .current_bytes
                    .saturating_sub(freed_bytes)
                    .saturating_add(allocated_bytes);
            }
            Operation::Try => {
                // i32 to permit setting a catch offset lower than the IP
                let catch_offset: i32 = self.next()?;
                // +1 to skip the POP_TRY that follows the try'd operations
                let catch_ip = (self.ip as i64)
                    .checked_add(catch_offset as i64 + 1)
                    .ok_or(VmError::IntegerOverflow)? as usize;
                let frame = ThrowFrame {
                    catch_ptr: catch_ip,
                    catch_symbol: self.current_symbol.clone(),
                    stack_start: self.stack.len(),
                    call_depth: self.stack_frames.len(),
                };
                self.throw_frames.push(frame);
            }
            Operation::PopTry => {
                if self.throw_frames.pop().is_none() {
                    return Err(VmError::UnexpectedPopTry);
                };
            }
            Operation::Throw => {
                let exception = self.pop_stack()?;
                let type_key: HogValue = HogLiteral::from("type".to_string()).into();
                let _type = exception.get_nested(&[type_key], &self.heap)?;
                let message_key = HogLiteral::from("message".to_string()).into();
                let message = exception.get_nested(&[message_key], &self.heap)?;
                // The other impls here have some special case handling that treats "Error" as a distinct type, but
                // as far as I can tell, a "hog error" is just a HogValue::Object with some specific properties, so
                // I'll just check those exist. hog is mostly duck-typed, based on the existing impls
                if _type.is_none() || message.is_none() {
                    return Err(VmError::InvalidException);
                };

                let Some(frame) = self.throw_frames.pop() else {
                    // TODO - we need some helper that'll deeply clone a HogValue::Object and product a HashMap<String, HogLiteral>, since
                    // this is escaping the VM, so heap references can't leak.
                    // let payload_key = HogLiteral::from("payload".to_string()).into();
                    // let payload = exception.get_nested(&[payload_key], &self.heap)?;
                    let _type: &str = _type.unwrap().deref(&self.heap)?.try_as()?;
                    let _message: &str = message.unwrap().deref(&self.heap)?.try_as()?;
                    return Err(VmError::UncaughtException(
                        _type.to_string(),
                        _message.to_string(),
                    ));
                };

                self.truncate_stack(frame.stack_start)?;
                self.stack_frames.truncate(frame.call_depth);
                self.ip = frame.catch_ptr;
                self.current_symbol = frame.catch_symbol;
                self.push_stack(exception)?;
            }
            Operation::Callable => {
                // Construct a locally callable object - this is how e.g. fn decl's work
                let name: String = self.next()?;
                let stack_arg_count: usize = self.next()?;
                let captured_arg_count: usize = self.next()?;
                let body_length: usize = self.next()?;
                let callable: Callable = LocalCallable {
                    name,
                    stack_arg_count,
                    capture_count: captured_arg_count,
                    ip: self.ip,
                    symbol: self.current_symbol.clone(), // Cross-module jumps are currently only done via CallGlobal
                }
                .into();
                self.push_stack(HogLiteral::Callable(callable))?;
                self.ip = self
                    .ip
                    .checked_add(body_length)
                    .ok_or(VmError::IntegerOverflow)?;
            }
            // A closure is a callable, plus some captured arguments from the scope
            // it was constructed in.
            Operation::Closure => {
                let callable: Callable = self.pop_stack_as()?;
                let capture_count: usize = self.next()?;
                // Irrefutable match for now
                let Callable::Local(unwrapped) = &callable;
                // Because captures are an implicit part of compilation, it's never valid
                // for them to be different from the number of captures in the callable.
                if capture_count != unwrapped.capture_count {
                    return Err(VmError::InvalidCall(
                        "invalid number of heap arguments".to_string(),
                    ));
                }
                let mut captures = Vec::with_capacity(capture_count);
                for _ in 0..capture_count {
                    // Indicates whether this captured argument is to a stack variable in this
                    // frames stack, or a captured argument in this frames captured arguments list
                    let is_local: bool = self.next()?;
                    // usize as closures can only capture stack variables in the current scope
                    let offset: usize = self.next()?;
                    if is_local {
                        let index = self
                            .current_frame_base()
                            .checked_add(offset)
                            .ok_or(VmError::IntegerOverflow)?;
                        captures.push(self.hoist(index)?);
                    } else {
                        captures.push(self.get_capture(offset)?);
                    }
                }

                let closure = Closure { callable, captures };
                self.push_stack(HogLiteral::Closure(closure))?;
            }
            Operation::CallLocal => {
                let closure: Closure = self.pop_stack_as()?;
                let arg_count: usize = self.next()?;
                let Callable::Local(callable) = &closure.callable;
                if arg_count > callable.stack_arg_count {
                    return Err(VmError::InvalidCall(format!(
                        "Too many args - expected {}, got {}",
                        callable.stack_arg_count, arg_count
                    )));
                }
                let null_args = callable.stack_arg_count.saturating_sub(arg_count);
                // For pure-hog function calls (calls to "local" callables), we just push a null onto the stack for each missing argument,
                // then construct the stack frame, and jump to the callable's frame ip. For other kinds of calls (which we don't support yet),
                // we'll have to do something more complicated
                for _ in 0..null_args {
                    self.push_stack(HogLiteral::Null)?;
                }
                let frame = CallFrame {
                    ret_ptr: self.ip,
                    ret_symbol: self.current_symbol.clone(),
                    stack_start: self.stack.len().saturating_sub(callable.stack_arg_count),
                    captures: closure.captures,
                };
                self.stack_frames.push(frame);
                self.current_symbol = callable.symbol.clone(); // Prep to jump across the module boundary, if that's what we're doing
                self.ip = callable.ip; // Do the jump
            }
            Operation::GetUpvalue => {
                let index: usize = self.next()?;
                let ptr = self.get_capture(index)?;
                self.push_stack(ptr)?;
            }
            Operation::SetUpvalue => {
                let index: usize = self.next()?;
                let ptr = self.get_capture(index)?;
                // If the top of the stack was a reference, we write that reference to the capture,
                // but if it was a literal, we write the literal to the heap location the capture points
                // to.
                let val = self.pop_stack()?;
                let new_size = val.size();
                match val {
                    HogValue::Lit(hog_literal) => {
                        let target = self.heap.get_mut(ptr)?;
                        let old_size = target.size();
                        *target = hog_literal;
                        // This doesn't assert the allocation is possible - the next one will fail, which is good enough
                        self.heap.current_bytes = self
                            .heap
                            .current_bytes
                            .saturating_sub(old_size)
                            .saturating_add(new_size)
                    }
                    HogValue::Ref(heap_reference) => self.set_capture(index, heap_reference)?,
                }
            }
            Operation::CloseUpvalue => {
                // The TS impl just pops here - I don't really understand why
                self.pop_stack()?;
            }
        }

        Ok(StepOutcome::Continue)
    }

    // Returns the first stack item in this call frames scope
    fn current_frame_base(&self) -> usize {
        if self.stack_frames.is_empty() {
            0
        } else {
            self.stack_frames[self.stack_frames.len() - 1].stack_start
        }
    }

    // Returns a ptr to the captured value in this frames scope, if there is one,
    // or an error if the index is out of bounds
    fn get_capture(&self, index: usize) -> Result<HeapReference, VmError> {
        let Some(frame) = self.stack_frames.last() else {
            return Err(VmError::NoFrame);
        };
        frame
            .captures
            .get(index)
            .cloned()
            .ok_or(VmError::CaptureOutOfBounds(index))
    }

    // Changes the location on the heap a capture points to, as distinct from changing the
    // value on the heap the capture points to. Think of this like storing a new pointer into
    // a variable name, vs. writing a new value into the variable itself
    fn set_capture(&mut self, index: usize, value: HeapReference) -> Result<(), VmError> {
        let Some(frame) = self.stack_frames.last_mut() else {
            return Err(VmError::NoFrame);
        };
        frame
            .captures
            .get_mut(index)
            .ok_or(VmError::CaptureOutOfBounds(index))
            .map(|capture| *capture = value)
    }

    fn next<T>(&mut self) -> Result<T, VmError>
    where
        T: DeserializeOwned + Any,
    {
        let next = self.context.get_bytecode(self.ip, &self.current_symbol)?;
        self.ip += 1;
        let next_type_name = next_type_name(next);
        let expected = std::any::type_name::<T>();

        serde_json::from_value(next.clone())
            .map_err(|_| VmError::InvalidValue(next_type_name, expected.to_string()))
    }

    fn pop_stack(&mut self) -> Result<HogValue, VmError> {
        if self.stack.len() <= self.current_frame_base() {
            return Err(VmError::StackUnderflow);
        }
        self.stack.pop().ok_or(VmError::StackUnderflow)
    }

    // As above, but with a handy pointer chase and a cast/unwrap. Necessarily clones
    // if the stack item was a reference.
    fn pop_stack_as<T>(&mut self) -> Result<T, VmError>
    where
        T: FromHogLiteral,
    {
        match self.pop_stack()? {
            HogValue::Lit(lit) => lit.try_into(), // Purely an optimisation to skip a clone
            other => other.deref(&self.heap)?.clone().try_into(),
        }
    }

    // Move a value from the stack onto the heap, replacing it with a reference to the heap value,
    // and returning a reference to it. If it was already a reference, return it.
    fn hoist(&mut self, idx: usize) -> Result<HeapReference, VmError> {
        let item = self.clone_stack_item(idx)?;
        match item {
            HogValue::Lit(lit) => {
                let ptr = self.heap.emplace(lit)?;
                self.set_stack_val(idx, ptr)?;
                Ok(ptr)
            }
            HogValue::Ref(ptr) => Ok(ptr),
        }
    }

    fn set_stack_val(&mut self, idx: usize, value: impl Into<HogValue>) -> Result<(), VmError> {
        // TODO - revisit this, idk about it
        self.stack
            .get_mut(idx)
            .ok_or(VmError::StackIndexOutOfBounds)
            .map(|v| *v = value.into())
    }

    fn truncate_stack(&mut self, new_len: usize) -> Result<(), VmError> {
        if new_len > self.stack.len() {
            return Err(VmError::StackIndexOutOfBounds);
        }
        self.stack.truncate(new_len);
        Ok(())
    }

    pub(crate) fn push_stack(&mut self, value: impl Into<HogValue>) -> Result<(), VmError> {
        if self.stack.len() >= self.context.max_stack_depth {
            return Err(VmError::StackOverflow);
        }
        self.stack.push(value.into());
        Ok(())
    }

    // TODO - we don't support function imports right now - most trivial programs don't need them,
    // and filters are generally trivial
    fn get_fn_reference(&self, _chain: &[HogValue]) -> Result<HogLiteral, VmError> {
        Err(VmError::NotImplemented("imports".to_string()))
    }

    fn clone_stack_item(&self, idx: usize) -> Result<HogValue, VmError> {
        self.stack.get(idx).cloned().ok_or(VmError::StackUnderflow)
    }

    fn prep_native_call(&self, name: String, args: Vec<HogValue>) -> StepOutcome {
        StepOutcome::NativeCall(name, args)
    }

    fn prep_cross_module_call(
        &mut self,
        symbol: Symbol,
        arg_count: usize,
    ) -> Result<StepOutcome, VmError> {
        // See CallLocal for details on how this works, but effectively, a cross-module call is just a
        // local call plus a current "module/function" change
        let to_call = self.context.get_symbol(&symbol)?;
        if arg_count > to_call.arg_count() {
            return Err(VmError::InvalidCall(format!(
                "Too many args - expected {}, got {}",
                to_call.arg_count(),
                arg_count
            )));
        }
        let null_args = to_call.arg_count().saturating_sub(arg_count);
        for _ in 0..null_args {
            self.push_stack(HogLiteral::Null)?;
        }
        let frame = CallFrame {
            ret_ptr: self.ip,
            ret_symbol: self.current_symbol.clone(),
            stack_start: self.stack.len().saturating_sub(to_call.arg_count()),
            captures: Vec::new(), // Cross module calls never involve captures
        };

        self.stack_frames.push(frame);
        self.current_symbol = Some(symbol);
        self.ip = 0;

        Ok(StepOutcome::Continue)
    }

    // Construct a hog value from a Json object. If the json object would be heap allocated
    // as a HogValue (e.g. if it's an array or object), then it will be allocated onto the heap,
    // and a reference will be returned. Nested json objects are flattened during allocation,
    // such that e.g. [[1,2],[3,4]] would lead to an array of [HeapReference, HeapReference] being
    // put into the heap, and a HeapReference being returned.
    //
    // This is a function on the VM, rather than being standalone, because hog values don't really
    // exist outside of the context of a VM (and specifically a heap). It could be a function on the
    // heap itself, though.
    pub fn json_to_hog(&mut self, json: JsonValue) -> Result<HogValue, VmError> {
        self.json_to_hog_impl(json, 0)
    }

    fn json_to_hog_impl(&mut self, current: JsonValue, depth: usize) -> Result<HogValue, VmError> {
        if depth > MAX_JSON_SERDE_DEPTH {
            return Err(VmError::OutOfResource(
                "json->hog deserialization depth".to_string(),
            ));
        };

        match current {
            JsonValue::Null => Ok(HogLiteral::Null.into()),
            JsonValue::Bool(b) => Ok(HogLiteral::Boolean(b).into()),
            JsonValue::Number(n) => Ok(HogLiteral::Number(n.into()).into()),
            JsonValue::String(s) => Ok(HogLiteral::String(s).into()),
            JsonValue::Array(arr) => {
                let mut values = Vec::new();
                for value in arr {
                    values.push(self.json_to_hog_impl(value, depth + 1)?);
                }
                let to_emplace = HogLiteral::Array(values);
                let ptr = self.heap.emplace(to_emplace)?;
                Ok(ptr.into())
            }
            JsonValue::Object(obj) => {
                let mut map = HashMap::new();
                for (key, value) in obj {
                    map.insert(key, self.json_to_hog_impl(value, depth + 1)?);
                }
                let to_emplace = HogLiteral::Object(map);
                let ptr = self.heap.emplace(to_emplace)?;
                Ok(ptr.into())
            }
        }
    }

    // Convert back from an arbitrary HogValue to a json Value. Again, this function exists on
    // the VM, because HogValues don't really exist in any other context.
    pub fn hog_to_json(&self, value: &HogValue) -> Result<JsonValue, VmError> {
        self.hog_to_json_impl(value, 0)
    }

    fn hog_to_json_impl(&self, value: &HogValue, depth: usize) -> Result<JsonValue, VmError> {
        if depth > MAX_JSON_SERDE_DEPTH {
            return Err(VmError::OutOfResource(
                "hog->json serialization depth".to_string(),
            ));
        };

        let val = value.deref(&self.heap)?;
        match val {
            HogLiteral::Null => Ok(JsonValue::Null),
            HogLiteral::Boolean(b) => Ok(JsonValue::Bool(*b)),
            HogLiteral::Number(n) => Ok(JsonValue::Number(n.clone().try_into()?)),
            HogLiteral::String(s) => Ok(JsonValue::String(s.clone())),
            HogLiteral::Array(arr) => {
                let mut json_arr = Vec::new();
                for elem in arr {
                    json_arr.push(self.hog_to_json_impl(elem, depth + 1)?);
                }
                Ok(JsonValue::Array(json_arr))
            }
            HogLiteral::Object(obj) => {
                let mut map = serde_json::Map::new();
                for (key, value) in obj {
                    map.insert(key.clone(), self.hog_to_json_impl(value, depth + 1)?);
                }
                Ok(JsonValue::Object(map))
            }
            HogLiteral::Callable(_) => Err(VmError::NotImplemented(
                "Callable serialisation".to_string(),
            )),
            HogLiteral::Closure(_) => {
                Err(VmError::NotImplemented("Closure serialisation".to_string()))
            }
        }
    }
}

// Helper function to simply run a program until it either finishes or returns an error
pub fn sync_execute(context: &ExecutionContext, print_debug: bool) -> Result<JsonValue, VmFailure> {
    let fail = |e, vm: Option<&HogVM>, step: usize| VmFailure {
        error: e,
        ip: vm.map_or(0, |vm| vm.ip),
        stack: vm.map_or(Vec::new(), |vm| vm.stack.clone()),
        step,
    };

    let mut vm = HogVM::new(context).map_err(|e| fail(e, None, 0))?;

    let mut i = 0;
    while i < context.max_steps {
        let res = if print_debug {
            vm.debug_step(&|s| println!("{s}"))
                .map_err(|e| fail(e, Some(&vm), i))?
        } else {
            vm.step().map_err(|e| fail(e, Some(&vm), i))?
        };

        match res {
            StepOutcome::Continue => {}
            StepOutcome::Finished(res) => return Ok(res),
            StepOutcome::NativeCall(name, args) => {
                match context.execute_native_function_call(&mut vm, &name, args) {
                    Ok(_) => {}
                    Err(err) => return Err(fail(err, Some(&vm), i)),
                };
            }
        }
        i += 1;
    }

    let err = VmError::OutOfResource("steps".to_string());

    Err(fail(err, Some(&vm), i))
}

fn next_type_name(next: &JsonValue) -> String {
    match next {
        JsonValue::Null => "null".to_string(),
        JsonValue::Bool(_) => "bool".to_string(),
        JsonValue::Number(_) => "number".to_string(),
        JsonValue::String(_) => "string".to_string(),
        JsonValue::Array(_) => "array".to_string(),
        JsonValue::Object(_) => "object".to_string(),
    }
}
