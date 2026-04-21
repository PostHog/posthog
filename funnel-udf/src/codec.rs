#![allow(dead_code)]

pub mod chunk;
pub mod header;
pub mod rowbinary;

use std::io;

#[derive(Debug)]
pub enum CodecError {
    Io(io::Error),
    InvalidNullMarker(u8),
    VarintOverflow,
    InvalidUtf8,
    ShapeMismatch,
    InvalidChunkHeader(String),
    UnknownType(String),
    TypeMismatch(String),
    IntOutOfRange {
        from: &'static str,
        to: &'static str,
        value: i128,
    },
    SchemaLen {
        got: usize,
        want: usize,
    },
}

impl std::fmt::Display for CodecError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "io error: {e}"),
            Self::InvalidNullMarker(b) => write!(f, "invalid Nullable marker byte: {b}"),
            Self::VarintOverflow => write!(f, "varint overflow: exceeded 10 bytes"),
            Self::InvalidUtf8 => write!(f, "invalid utf-8 in String value"),
            Self::ShapeMismatch => {
                write!(f, "PropVal variant does not match declared BreakdownShape")
            }
            Self::InvalidChunkHeader(s) => write!(f, "invalid chunk header: {s:?}"),
            Self::UnknownType(s) => write!(f, "unsupported ClickHouse type from header: {s}"),
            Self::TypeMismatch(s) => write!(f, "type mismatch: {s}"),
            Self::IntOutOfRange { from, to, value } => {
                write!(
                    f,
                    "integer out of range: {value} ({from}) does not fit in {to}"
                )
            }
            Self::SchemaLen { got, want } => {
                write!(f, "block header declares {got} columns, expected {want}")
            }
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
