#![allow(dead_code)]

pub mod chunk;
pub mod msgpack;

use std::io;

#[derive(Debug)]
pub enum CodecError {
    Io(io::Error),
    InvalidUtf8,
    UnexpectedNull,
    ShapeMismatch,
    InvalidChunkHeader(String),
    UnexpectedEof,
    TypeMismatch(String),
    IntOutOfRange {
        from: &'static str,
        to: &'static str,
        value: i128,
    },
    Schema(String),
}

impl std::fmt::Display for CodecError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "io error: {e}"),
            Self::InvalidUtf8 => write!(f, "invalid utf-8 in String value"),
            Self::UnexpectedNull => {
                write!(
                    f,
                    "unexpected nil in Nullable slot — caller requires non-null"
                )
            }
            Self::ShapeMismatch => {
                write!(f, "PropVal variant does not match declared BreakdownShape")
            }
            Self::InvalidChunkHeader(s) => write!(f, "invalid chunk header: {s:?}"),
            Self::UnexpectedEof => write!(f, "unexpected eof mid-row"),
            Self::TypeMismatch(s) => write!(f, "type mismatch: {s}"),
            Self::IntOutOfRange { from, to, value } => {
                write!(
                    f,
                    "integer out of range: {value} ({from}) does not fit in {to}"
                )
            }
            Self::Schema(s) => write!(f, "schema error: {s}"),
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
