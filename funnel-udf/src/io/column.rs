// Slot-level readers for the declared UDF argument shapes, on top of
// `codec::msgpack`. MsgPack is self-describing, so these readers don't
// take a declared-type parameter the way RowBinary's did — they just
// pull the next MsgPack value off the stream and coerce/range-check
// into the expected Rust type.

use std::io::Read;

use crate::codec::msgpack;
use crate::codec::{CodecError, CodecResult};

pub fn read_u8_col<R: Read>(r: &mut R) -> CodecResult<u8> {
    msgpack::read_u8(r)
}

pub fn read_u64_col<R: Read>(r: &mut R) -> CodecResult<u64> {
    msgpack::read_u64(r)
}

pub fn read_u32_col<R: Read>(r: &mut R) -> CodecResult<u32> {
    msgpack::read_u32(r)
}

/// Read a `Nullable(Float64)` — errors if the value is nil. Funnel invariant:
/// event timestamps are never null by the time they reach the UDF.
pub fn read_nullable_f64<R: Read>(r: &mut R) -> CodecResult<f64> {
    msgpack::read_f64_nullable(r)
}

/// Read a plain `String` column as raw bytes.
pub fn read_string<R: Read>(r: &mut R) -> CodecResult<Vec<u8>> {
    msgpack::read_bytes(r)
}

/// Read a `Nullable(String)` as raw bytes — errors on nil.
/// Funnel invariant: `ifNull(..., '')` upstream means nulls never arrive.
pub fn read_nullable_string<R: Read>(r: &mut R) -> CodecResult<Vec<u8>> {
    msgpack::read_bytes_nullable(r)
}

/// Read an `Array(Int8)`.
pub fn read_array_i8<R: Read>(r: &mut R) -> CodecResult<Vec<i8>> {
    let len = msgpack::read_array_len(r)?;
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        out.push(msgpack::read_i8(r)?);
    }
    Ok(out)
}

/// Read the length prefix of a top-level array. Used by callers that
/// need the element count ahead of the element reads.
pub fn read_array_len<R: Read>(r: &mut R) -> CodecResult<usize> {
    msgpack::read_array_len(r)
}

/// Read a tuple — MsgPack encodes tuples as fixed-length arrays. We verify
/// the arity matches what we expect before letting the caller pull elements.
pub fn read_tuple_arity<R: Read>(r: &mut R, expected: usize, ctx: &str) -> CodecResult<()> {
    let got = msgpack::read_array_len(r)?;
    if got != expected {
        return Err(CodecError::Schema(format!(
            "{ctx}: expected tuple of {expected} elements, got {got}"
        )));
    }
    Ok(())
}

pub fn read_uuid<R: Read>(r: &mut R) -> CodecResult<uuid::Uuid> {
    msgpack::read_uuid(r)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::msgpack::{write_array_len, write_bin, write_nil, write_sint, write_uint};
    use std::io::Cursor;

    #[test]
    fn u8_accepts_wider_int_on_wire() {
        let mut buf = Vec::new();
        write_uint(&mut buf, 42).unwrap();
        let mut cur = Cursor::new(buf);
        assert_eq!(read_u8_col(&mut cur).unwrap(), 42);
    }

    #[test]
    fn u8_rejects_out_of_range() {
        let mut buf = Vec::new();
        write_uint(&mut buf, 300).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_u8_col(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::IntOutOfRange { .. }));
    }

    #[test]
    fn u64_rejects_negative() {
        let mut buf = Vec::new();
        write_sint(&mut buf, -1).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_u64_col(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::IntOutOfRange { .. }));
    }

    #[test]
    fn array_i8_reads_mixed_widths() {
        let mut buf = Vec::new();
        write_array_len(&mut buf, 3).unwrap();
        write_sint(&mut buf, 1).unwrap(); // fixpos
        write_sint(&mut buf, -2).unwrap(); // fixneg
        write_sint(&mut buf, 3).unwrap();
        let mut cur = Cursor::new(buf);
        assert_eq!(read_array_i8(&mut cur).unwrap(), vec![1, -2, 3]);
    }

    #[test]
    fn nullable_string_accepts_plain_bytes() {
        let mut buf = Vec::new();
        write_bin(&mut buf, b"hello").unwrap();
        let mut cur = Cursor::new(buf);
        assert_eq!(read_nullable_string(&mut cur).unwrap(), b"hello");
    }

    #[test]
    fn nullable_string_errors_on_nil() {
        let mut buf = Vec::new();
        write_nil(&mut buf).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_nullable_string(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::UnexpectedNull));
    }
}
