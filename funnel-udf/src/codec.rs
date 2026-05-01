pub mod chunk;
pub mod header;
pub mod rowbinary;

use std::io;

#[derive(Debug)]
pub enum CodecError {
    Io(io::Error),
    InvalidChunkHeader(String),
    UnknownType(String),
    TypeMismatch(String),
    SchemaLen { got: usize, want: usize },
    CorruptWire(String),
}

impl std::fmt::Display for CodecError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "io error: {e}"),
            Self::InvalidChunkHeader(s) => write!(f, "invalid chunk header: {s:?}"),
            Self::UnknownType(s) => write!(f, "unsupported ClickHouse type from header: {s}"),
            Self::TypeMismatch(s) => write!(f, "type mismatch: {s}"),
            Self::SchemaLen { got, want } => {
                write!(f, "block header declares {got} columns, expected {want}")
            }
            Self::CorruptWire(s) => write!(f, "corrupt wire: {s}"),
        }
    }
}

impl std::error::Error for CodecError {}

impl From<io::Error> for CodecError {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

pub type CodecResult<T> = std::result::Result<T, CodecError>;
