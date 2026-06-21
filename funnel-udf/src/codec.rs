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

/// Ceiling on how many elements we pre-allocate before reading a sequence whose
/// length came off the wire. The length prefix is whatever the (possibly corrupt
/// or desynced) stream claims, and `Vec::with_capacity(huge)` aborts the process
/// — which ClickHouse surfaces as the opaque `CHILD_WAS_NOT_EXITED_NORMALLY` with
/// the real error hidden. Capacity is only a hint, so legitimately longer
/// sequences still grow on demand; capping the pre-allocation costs nothing on
/// the happy path while removing the abort vector.
const PREALLOC_CAP: usize = 1024;

/// `Vec::with_capacity` clamped to `PREALLOC_CAP` — use for every allocation
/// whose capacity comes from a wire-supplied length (array lengths, chunk row
/// counts, column counts). Lives in `codec` so both the codec layer and `io` can
/// share one cap.
pub fn prealloc<T>(len: usize) -> Vec<T> {
    Vec::with_capacity(len.min(PREALLOC_CAP))
}

#[cfg(test)]
mod tests {
    use super::*;

    // A wire-claimed length far beyond the cap must not pre-allocate beyond it —
    // this is the allocation-abort vector `prealloc` exists to remove. Without
    // the cap, `Vec::with_capacity(usize::MAX)` aborts the process.
    #[test]
    fn prealloc_caps_huge_wire_length() {
        assert!(prealloc::<u8>(usize::MAX).capacity() <= PREALLOC_CAP);
        assert!(prealloc::<u64>(10_000_000).capacity() <= PREALLOC_CAP);
    }

    // Below the cap, the exact length is still reserved — the cap only clamps the
    // pathological end, it doesn't penalise normal sizes.
    #[test]
    fn prealloc_reserves_exact_below_cap() {
        assert_eq!(prealloc::<u8>(0).capacity(), 0);
        assert_eq!(prealloc::<u8>(8).capacity(), 8);
    }
}
