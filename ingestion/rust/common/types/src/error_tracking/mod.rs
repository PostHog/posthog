mod exception;
mod frame;

pub use exception::*;
pub use frame::*;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Context {
    pub before: Vec<ContextLine>,
    pub line: ContextLine,
    pub after: Vec<ContextLine>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct ContextLine {
    pub number: u32,
    pub line: String,
}
