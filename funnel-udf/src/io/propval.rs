// Reading / writing breakdown values through the MsgPack codec.
//
// MsgPack is self-describing: a breakdown value's wire type (bin/str, int,
// array) tells us which PropVal variant it is without a separate header.
// We still use `BreakdownShape` because the UDF has to emit results in a
// single consistent layout (one slot in the output tuple), and that layout
// is decided once per invocation by peeking at the first incoming breakdown.

use std::io::{BufRead, Write};

use rmp::Marker;

use crate::codec::msgpack;
#[cfg(test)]
use crate::codec::msgpack::peek_marker;
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{read_array_len, read_nullable_string, read_string};
use crate::types::{BreakdownShape, Bytes, PropVal};

/// Read one breakdown value under the given shape.
pub fn read_propval<R: BufRead>(r: &mut R, shape: BreakdownShape) -> CodecResult<PropVal> {
    match shape {
        BreakdownShape::NullableString => Ok(PropVal::String(Bytes(read_nullable_string(r)?))),
        BreakdownShape::ArrayString => {
            let n = read_array_len(r)?;
            let mut out = Vec::with_capacity(n);
            for _ in 0..n {
                out.push(Bytes(read_string(r)?));
            }
            Ok(PropVal::Vec(out))
        }
        BreakdownShape::U64 => Ok(PropVal::Int(msgpack::read_u64(r)?)),
    }
}

/// Read the full `prop_vals` array as a list of PropVals under the shape.
pub fn read_propval_array<R: BufRead>(
    r: &mut R,
    shape: BreakdownShape,
) -> CodecResult<Vec<PropVal>> {
    let n = read_array_len(r)?;
    let mut out = Vec::with_capacity(n);
    for _ in 0..n {
        out.push(read_propval(r, shape)?);
    }
    Ok(out)
}

/// Detect the breakdown shape from the next MsgPack marker on the wire.
/// Returns None if the marker is not recognized as a breakdown shape tag
/// (caller should produce a meaningful error with context).
pub fn shape_from_marker(m: Marker) -> Option<BreakdownShape> {
    match m {
        Marker::FixPos(_)
        | Marker::FixNeg(_)
        | Marker::U8
        | Marker::U16
        | Marker::U32
        | Marker::U64
        | Marker::I8
        | Marker::I16
        | Marker::I32
        | Marker::I64 => Some(BreakdownShape::U64),
        Marker::Null
        | Marker::FixStr(_)
        | Marker::Str8
        | Marker::Str16
        | Marker::Str32
        | Marker::Bin8
        | Marker::Bin16
        | Marker::Bin32 => Some(BreakdownShape::NullableString),
        Marker::FixArray(_) | Marker::Array16 | Marker::Array32 => {
            Some(BreakdownShape::ArrayString)
        }
        _ => None,
    }
}

/// Peek the next wire marker to figure out the breakdown shape without
/// consuming anything. Returns None at EOF.
#[cfg(test)]
pub fn peek_shape<R: BufRead>(r: &mut R) -> CodecResult<Option<BreakdownShape>> {
    let m = peek_marker(r)?;
    Ok(m.and_then(shape_from_marker))
}

// -------- Write side --------

pub fn write_propval<W: Write>(w: &mut W, p: &PropVal, shape: BreakdownShape) -> CodecResult<()> {
    match (shape, p) {
        (BreakdownShape::NullableString, PropVal::String(b)) => msgpack::write_bin(w, &b.0),
        (BreakdownShape::ArrayString, PropVal::Vec(v)) => {
            msgpack::write_array_len(w, v.len() as u32)?;
            for b in v {
                msgpack::write_bin(w, &b.0)?;
            }
            Ok(())
        }
        (BreakdownShape::U64, PropVal::Int(n)) => msgpack::write_uint(w, *n),
        _ => Err(CodecError::ShapeMismatch),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::msgpack::{write_array_len, write_bin, write_nil, write_uint};
    use std::io::Cursor;

    fn peek(buf: Vec<u8>) -> Option<BreakdownShape> {
        let mut cur = Cursor::new(buf);
        peek_shape(&mut cur).unwrap()
    }

    #[test]
    fn shape_from_nullable_string_bin() {
        let mut buf = Vec::new();
        write_bin(&mut buf, b"en").unwrap();
        assert_eq!(peek(buf), Some(BreakdownShape::NullableString));
    }

    #[test]
    fn shape_from_nil_is_nullable_string() {
        let mut buf = Vec::new();
        write_nil(&mut buf).unwrap();
        assert_eq!(peek(buf), Some(BreakdownShape::NullableString));
    }

    #[test]
    fn shape_from_uint_is_u64() {
        let mut buf = Vec::new();
        write_uint(&mut buf, 42).unwrap();
        assert_eq!(peek(buf), Some(BreakdownShape::U64));
    }

    #[test]
    fn shape_from_array_is_array_string() {
        let mut buf = Vec::new();
        write_array_len(&mut buf, 0).unwrap();
        assert_eq!(peek(buf), Some(BreakdownShape::ArrayString));
    }

    #[test]
    fn read_propval_nullable_bytes() {
        let mut buf = Vec::new();
        write_bin(&mut buf, b"hi").unwrap();
        let mut cur = Cursor::new(buf);
        let got = read_propval(&mut cur, BreakdownShape::NullableString).unwrap();
        assert_eq!(got, PropVal::String(Bytes(b"hi".to_vec())));
    }

    #[test]
    fn read_propval_u64() {
        let mut buf = Vec::new();
        write_uint(&mut buf, 1209600).unwrap();
        let mut cur = Cursor::new(buf);
        let got = read_propval(&mut cur, BreakdownShape::U64).unwrap();
        assert_eq!(got, PropVal::Int(1209600));
    }

    #[test]
    fn non_utf8_bytes_survive() {
        let bad = vec![0xff, 0xfe, 0x00, 0x80];
        let mut buf = Vec::new();
        write_bin(&mut buf, &bad).unwrap();
        let mut cur = Cursor::new(buf);
        let got = read_propval(&mut cur, BreakdownShape::NullableString).unwrap();
        assert_eq!(got, PropVal::String(Bytes(bad)));
    }
}
