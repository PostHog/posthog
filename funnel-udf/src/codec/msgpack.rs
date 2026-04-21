// MsgPack read/write helpers tailored to ClickHouse's `MsgPack` format.
//
// ClickHouse wire conventions worth knowing:
//   - `String` columns are serialized as MsgPack `bin` (type-preserving for
//     non-UTF-8 bytes). We also accept `str` on read.
//   - `Nullable(T)` is `nil` when null, otherwise the inner T's encoding.
//   - `UUID` is a `fixext 16` with type=2 and the 16 bytes in RFC 4122 order
//     (NOT the hi/lo u64 swap that RowBinary uses).
//   - Tuples serialize as `array` of the fixed element count.
//   - Int widths on the wire are MsgPack-picked (tightest representation) and
//     independent of the declared CH column type — the reader narrows/widens
//     as needed.

use std::io::{BufRead, Read, Write};

use byteorder::{BigEndian, ReadBytesExt};
use rmp::decode::{self, ValueReadError};
use rmp::encode::{self};
use rmp::Marker;
use uuid::Uuid;

use crate::codec::{CodecError, CodecResult};

impl From<ValueReadError> for CodecError {
    fn from(e: ValueReadError) -> Self {
        match e {
            ValueReadError::InvalidMarkerRead(e) | ValueReadError::InvalidDataRead(e) => {
                CodecError::Io(e)
            }
            ValueReadError::TypeMismatch(m) => {
                CodecError::TypeMismatch(format!("msgpack marker mismatch: {m:?}"))
            }
        }
    }
}

fn map_num_err(e: rmp::decode::NumValueReadError) -> CodecError {
    match e {
        rmp::decode::NumValueReadError::InvalidMarkerRead(e)
        | rmp::decode::NumValueReadError::InvalidDataRead(e) => CodecError::Io(e),
        rmp::decode::NumValueReadError::TypeMismatch(m) => {
            CodecError::TypeMismatch(format!("msgpack int marker mismatch: {m:?}"))
        }
        rmp::decode::NumValueReadError::OutOfRange => {
            CodecError::TypeMismatch("msgpack int out of range".into())
        }
    }
}

/// Peek at the next marker without consuming it. Returns `None` at EOF.
pub fn peek_marker<R: BufRead>(r: &mut R) -> CodecResult<Option<Marker>> {
    let buf = r.fill_buf().map_err(CodecError::Io)?;
    if buf.is_empty() {
        return Ok(None);
    }
    Ok(Some(Marker::from_u8(buf[0])))
}

/// Read any MsgPack integer (positive or negative fixint, uint8/16/32/64,
/// int8/16/32/64) into an i128 so we can range-check narrower targets.
pub fn read_int_as_i128<R: Read>(r: &mut R) -> CodecResult<i128> {
    // rmp::decode::read_int widens to any primitive; use i128 to cover UInt64.
    let marker = decode::read_marker(r).map_err(|e| match e {
        rmp::decode::MarkerReadError(io_err) => CodecError::Io(io_err),
    })?;
    match marker {
        Marker::FixPos(v) => Ok(v as i128),
        Marker::FixNeg(v) => Ok(v as i128),
        Marker::U8 => Ok(r.read_u8().map_err(CodecError::Io)? as i128),
        Marker::U16 => Ok(r.read_u16::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::U32 => Ok(r.read_u32::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::U64 => Ok(r.read_u64::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::I8 => Ok(r.read_i8().map_err(CodecError::Io)? as i128),
        Marker::I16 => Ok(r.read_i16::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::I32 => Ok(r.read_i32::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::I64 => Ok(r.read_i64::<BigEndian>().map_err(CodecError::Io)? as i128),
        Marker::Null => Err(CodecError::UnexpectedNull),
        other => Err(CodecError::TypeMismatch(format!(
            "expected integer, got marker {other:?}"
        ))),
    }
}

pub fn read_u8<R: Read>(r: &mut R) -> CodecResult<u8> {
    let v = read_int_as_i128(r)?;
    if !(0..=255).contains(&v) {
        return Err(CodecError::IntOutOfRange {
            from: "msgpack int",
            to: "u8",
            value: v,
        });
    }
    Ok(v as u8)
}

pub fn read_u32<R: Read>(r: &mut R) -> CodecResult<u32> {
    let v = read_int_as_i128(r)?;
    if v < 0 || v > u32::MAX as i128 {
        return Err(CodecError::IntOutOfRange {
            from: "msgpack int",
            to: "u32",
            value: v,
        });
    }
    Ok(v as u32)
}

pub fn read_u64<R: Read>(r: &mut R) -> CodecResult<u64> {
    let v = read_int_as_i128(r)?;
    if v < 0 || v > u64::MAX as i128 {
        return Err(CodecError::IntOutOfRange {
            from: "msgpack int",
            to: "u64",
            value: v,
        });
    }
    Ok(v as u64)
}

pub fn read_i8<R: Read>(r: &mut R) -> CodecResult<i8> {
    let v = read_int_as_i128(r)?;
    if !(i8::MIN as i128..=i8::MAX as i128).contains(&v) {
        return Err(CodecError::IntOutOfRange {
            from: "msgpack int",
            to: "i8",
            value: v,
        });
    }
    Ok(v as i8)
}

/// Read bin or str into a byte vector. Both are length-prefixed byte arrays
/// in MsgPack; the only difference is str asserts UTF-8, which we ignore.
pub fn read_bytes<R: Read>(r: &mut R) -> CodecResult<Vec<u8>> {
    let marker =
        decode::read_marker(r).map_err(|rmp::decode::MarkerReadError(e)| CodecError::Io(e))?;
    let len = match marker {
        Marker::FixStr(n) => n as usize,
        Marker::Str8 | Marker::Bin8 => r.read_u8().map_err(CodecError::Io)? as usize,
        Marker::Str16 | Marker::Bin16 => {
            r.read_u16::<BigEndian>().map_err(CodecError::Io)? as usize
        }
        Marker::Str32 | Marker::Bin32 => {
            r.read_u32::<BigEndian>().map_err(CodecError::Io)? as usize
        }
        Marker::Null => return Err(CodecError::UnexpectedNull),
        other => {
            return Err(CodecError::TypeMismatch(format!(
                "expected bin/str, got {other:?}"
            )));
        }
    };
    let mut buf = vec![0u8; len];
    r.read_exact(&mut buf).map_err(CodecError::Io)?;
    Ok(buf)
}

/// Read a `Nullable(bin/str)`: returns the inner bytes or error on nil.
/// Funnel invariant: breakdown fields are never null by the time they reach us.
pub fn read_bytes_nullable<R: Read>(r: &mut R) -> CodecResult<Vec<u8>> {
    let start = r.bytes().next();
    // We can't easily peek without a buffer; instead, read_marker and branch.
    // Rewind by re-constructing: read_marker consumes one byte; we always need
    // to consume it anyway since nil is a single byte.
    // To avoid putting the byte back we just handle marker inline.
    // But we already consumed one byte here — use a tiny adapter.
    let first = start
        .ok_or(CodecError::UnexpectedEof)?
        .map_err(CodecError::Io)?;
    match Marker::from_u8(first) {
        Marker::Null => Err(CodecError::UnexpectedNull),
        Marker::FixStr(n) => {
            let mut buf = vec![0u8; n as usize];
            r.read_exact(&mut buf).map_err(CodecError::Io)?;
            Ok(buf)
        }
        Marker::Str8 | Marker::Bin8 => {
            let len = r.read_u8().map_err(CodecError::Io)? as usize;
            let mut buf = vec![0u8; len];
            r.read_exact(&mut buf).map_err(CodecError::Io)?;
            Ok(buf)
        }
        Marker::Str16 | Marker::Bin16 => {
            let len = r.read_u16::<BigEndian>().map_err(CodecError::Io)? as usize;
            let mut buf = vec![0u8; len];
            r.read_exact(&mut buf).map_err(CodecError::Io)?;
            Ok(buf)
        }
        Marker::Str32 | Marker::Bin32 => {
            let len = r.read_u32::<BigEndian>().map_err(CodecError::Io)? as usize;
            let mut buf = vec![0u8; len];
            r.read_exact(&mut buf).map_err(CodecError::Io)?;
            Ok(buf)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected bin/str/nil, got {other:?}"
        ))),
    }
}

/// Read `Nullable(Float64)` — float or nil.
pub fn read_f64_nullable<R: Read>(r: &mut R) -> CodecResult<f64> {
    let marker =
        decode::read_marker(r).map_err(|rmp::decode::MarkerReadError(e)| CodecError::Io(e))?;
    match marker {
        Marker::F64 => r.read_f64::<BigEndian>().map_err(CodecError::Io),
        Marker::F32 => Ok(r.read_f32::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::Null => Err(CodecError::UnexpectedNull),
        // Ints are sometimes emitted for whole-number floats; be permissive.
        Marker::FixPos(v) => Ok(v as f64),
        Marker::FixNeg(v) => Ok(v as f64),
        Marker::U8 => Ok(r.read_u8().map_err(CodecError::Io)? as f64),
        Marker::U16 => Ok(r.read_u16::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::U32 => Ok(r.read_u32::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::U64 => Ok(r.read_u64::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::I8 => Ok(r.read_i8().map_err(CodecError::Io)? as f64),
        Marker::I16 => Ok(r.read_i16::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::I32 => Ok(r.read_i32::<BigEndian>().map_err(CodecError::Io)? as f64),
        Marker::I64 => Ok(r.read_i64::<BigEndian>().map_err(CodecError::Io)? as f64),
        other => Err(CodecError::TypeMismatch(format!(
            "expected float/int/nil, got {other:?}"
        ))),
    }
}

/// Read an array length prefix. Returns the count; caller reads elements.
pub fn read_array_len<R: Read>(r: &mut R) -> CodecResult<usize> {
    decode::read_array_len(r)
        .map(|n| n as usize)
        .map_err(Into::into)
}

/// Read a CH UUID: fixext 16 with type=2, 16 bytes RFC 4122 order.
pub fn read_uuid<R: Read>(r: &mut R) -> CodecResult<Uuid> {
    let marker =
        decode::read_marker(r).map_err(|rmp::decode::MarkerReadError(e)| CodecError::Io(e))?;
    let (expected_len, have_typeid) = match marker {
        Marker::FixExt16 => (16, true),
        Marker::Ext8 => {
            let len = r.read_u8().map_err(CodecError::Io)? as usize;
            if len != 16 {
                return Err(CodecError::TypeMismatch(format!(
                    "expected ext-16 for UUID, got ext-{len}"
                )));
            }
            (16, true)
        }
        other => {
            return Err(CodecError::TypeMismatch(format!(
                "expected ext UUID, got {other:?}"
            )));
        }
    };
    if have_typeid {
        let typeid = r.read_i8().map_err(CodecError::Io)?;
        if typeid != 2 {
            return Err(CodecError::TypeMismatch(format!(
                "expected UUID ext type=2, got {typeid}"
            )));
        }
    }
    let mut bytes = [0u8; 16];
    r.read_exact(&mut bytes).map_err(CodecError::Io)?;
    let _ = expected_len;
    Ok(Uuid::from_bytes(bytes))
}

// -------- Write side --------

pub fn write_nil<W: Write>(w: &mut W) -> CodecResult<()> {
    encode::write_nil(w).map_err(|e| CodecError::Io(e.into()))
}

pub fn write_uint<W: Write>(w: &mut W, v: u64) -> CodecResult<()> {
    encode::write_uint(w, v)
        .map_err(|e| CodecError::Io(e.into()))
        .map(|_| ())
}

pub fn write_sint<W: Write>(w: &mut W, v: i64) -> CodecResult<()> {
    encode::write_sint(w, v)
        .map_err(|e| CodecError::Io(e.into()))
        .map(|_| ())
}

pub fn write_f64<W: Write>(w: &mut W, v: f64) -> CodecResult<()> {
    encode::write_f64(w, v).map_err(|e| CodecError::Io(e.into()))
}

pub fn write_array_len<W: Write>(w: &mut W, len: u32) -> CodecResult<()> {
    encode::write_array_len(w, len)
        .map_err(|e| CodecError::Io(e.into()))
        .map(|_| ())
}

pub fn write_bin<W: Write>(w: &mut W, bytes: &[u8]) -> CodecResult<()> {
    encode::write_bin(w, bytes).map_err(|e| CodecError::Io(e.into()))
}

/// Write a CH UUID as fixext-16 type=2, bytes in RFC 4122 order.
pub fn write_uuid<W: Write>(w: &mut W, u: Uuid) -> CodecResult<()> {
    // fixext16 marker is 0xd8 followed by type id byte, then 16 bytes.
    encode::write_ext_meta(w, 16, 2).map_err(|e| CodecError::Io(e.into()))?;
    w.write_all(u.as_bytes()).map_err(CodecError::Io)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn uuid_roundtrip() {
        let u = Uuid::parse_str("01020304-0506-0708-090a-0b0c0d0e0f10").unwrap();
        let mut buf = Vec::new();
        write_uuid(&mut buf, u).unwrap();
        // Expect: d8 02 + 16 bytes in RFC 4122 order
        assert_eq!(buf[0], 0xd8);
        assert_eq!(buf[1], 0x02);
        assert_eq!(&buf[2..], u.as_bytes());

        let mut cur = Cursor::new(buf);
        assert_eq!(read_uuid(&mut cur).unwrap(), u);
    }

    #[test]
    fn int_widening() {
        // Write u32 300, read as u8 → out of range
        let mut buf = Vec::new();
        write_uint(&mut buf, 300).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_u8(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::IntOutOfRange { .. }));
    }

    #[test]
    fn negative_rejected_by_u64() {
        let mut buf = Vec::new();
        write_sint(&mut buf, -1).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_u64(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::IntOutOfRange { .. }));
    }

    #[test]
    fn bytes_roundtrip_preserves_non_utf8() {
        let bad = vec![0xff, 0xfe, 0x00, 0x80];
        let mut buf = Vec::new();
        write_bin(&mut buf, &bad).unwrap();
        let mut cur = Cursor::new(buf);
        assert_eq!(read_bytes(&mut cur).unwrap(), bad);
    }

    #[test]
    fn nullable_bytes_errors_on_nil() {
        let mut buf = Vec::new();
        write_nil(&mut buf).unwrap();
        let mut cur = Cursor::new(buf);
        let err = read_bytes_nullable(&mut cur).unwrap_err();
        assert!(matches!(err, CodecError::UnexpectedNull));
    }
}
