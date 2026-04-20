use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum PropVal {
    String(String),
    Vec(Vec<String>),
    Int(u64),
    VecInt(Vec<u64>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BreakdownShape {
    NullableString,
    ArrayString,
    U64,
}

impl BreakdownShape {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "nullable_string" => Some(Self::NullableString),
            "array_string" => Some(Self::ArrayString),
            "u64" => Some(Self::U64),
            _ => None,
        }
    }
}
