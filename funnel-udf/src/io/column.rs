// Permissive leaves, strict structure. Two things to know:
//
//   1. ClickHouse puts the source expression's inferred type on the wire, not the
//      UDF's XML-declared arg type. A UInt8 slot routinely arrives as Int64
//      because HogQL emits integer literals as Int64. We widen through i128 and
//      narrow with bounds checks. LowCardinality wrappers are transparent in
//      RowBinary, so we peel them.
//
//   2. The XML declares several slots Nullable(T) but ClickHouse may send plain T
//      when the source expression is statically non-null. We accept both and
//      treat plain T as always-non-null; the `ifNull(..., '')` / `toFloat()`
//      upstream makes this safe.
//
// Tuple arity and column count are checked exactly — a mismatch there means the
// UDF contract is broken.

use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::RowBinaryRead;
use crate::codec::{CodecError, CodecResult};

fn read_int_any<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<(i128, &'static str)> {
    match t.remove_low_cardinality() {
        DataTypeNode::UInt8 => Ok((r.read_u8()? as i128, "UInt8")),
        DataTypeNode::UInt16 => Ok((r.read_u16_le()? as i128, "UInt16")),
        DataTypeNode::UInt32 => Ok((r.read_u32_le()? as i128, "UInt32")),
        DataTypeNode::UInt64 => Ok((r.read_u64_le()? as i128, "UInt64")),
        DataTypeNode::Int8 => Ok((r.read_i8()? as i128, "Int8")),
        DataTypeNode::Int16 => Ok((r.read_i16_le()? as i128, "Int16")),
        DataTypeNode::Int32 => Ok((r.read_i32_le()? as i128, "Int32")),
        DataTypeNode::Int64 => Ok((r.read_i64_le()? as i128, "Int64")),
        DataTypeNode::Bool => Ok((r.read_u8()? as i128, "Bool")),
        other => Err(CodecError::TypeMismatch(format!(
            "expected integer type, got {other}"
        ))),
    }
}

pub fn read_u8_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<u8> {
    let (v, from) = read_int_any(r, t)?;
    if !(0..=255).contains(&v) {
        return Err(CodecError::IntOutOfRange {
            from,
            to: "UInt8",
            value: v,
        });
    }
    Ok(v as u8)
}

pub fn read_u64_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<u64> {
    let (v, from) = read_int_any(r, t)?;
    if v < 0 || v > u64::MAX as i128 {
        return Err(CodecError::IntOutOfRange {
            from,
            to: "UInt64",
            value: v,
        });
    }
    Ok(v as u64)
}

fn narrow_to_i8(v: i128, from: &'static str) -> CodecResult<i8> {
    if (i8::MIN as i128..=i8::MAX as i128).contains(&v) {
        Ok(v as i8)
    } else {
        Err(CodecError::IntOutOfRange {
            from,
            to: "Int8",
            value: v,
        })
    }
}

pub fn read_nullable_f64<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<f64> {
    match t {
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::Float64) => {
            match r.read_u8()? {
                0 => r.read_f64_le(),
                1 => Err(CodecError::TypeMismatch(
                    "null timestamp — funnel ordering requires a concrete value".into(),
                )),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        DataTypeNode::Float64 => r.read_f64_le(),
        DataTypeNode::Float32 => {
            let mut b = [0u8; 4];
            r.read_exact(&mut b)?;
            Ok(f32::from_le_bytes(b) as f64)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Float64 or Nullable(Float64), got {other}"
        ))),
    }
}

pub fn read_string<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<Vec<u8>> {
    match t.remove_low_cardinality() {
        DataTypeNode::String => r.read_bytes(),
        DataTypeNode::FixedString(n) => {
            let mut buf = vec![0u8; *n];
            r.read_exact(&mut buf)?;
            Ok(buf)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected String, got {other}"
        ))),
    }
}

// Null breakdown maps to an empty string. The funnel-trends breakdown returns
// `""` as a valid bucket when the source expression is NULL (matches upstream
// ifNull semantics and the existing JSONEachRow behavior).
pub fn read_nullable_string<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<u8>> {
    match t.remove_low_cardinality() {
        DataTypeNode::Nullable(inner) if matches!(**inner, DataTypeNode::String) => {
            match r.read_u8()? {
                0 => r.read_bytes(),
                1 => Ok(Vec::new()),
                b => Err(CodecError::InvalidNullMarker(b)),
            }
        }
        DataTypeNode::String => r.read_bytes(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected String or Nullable(String), got {other}"
        ))),
    }
}

/// Reads an array whose elements should be Int8. Accepts any int-family element
/// type and narrows per-element with a bounds check. `Array(Nothing)` (CH's type
/// for the empty literal `[]`) is accepted as an empty array regardless of length
/// prefix.
pub fn read_array_i8<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<i8>> {
    let inner = array_elem(t, "Array(Int8)")?;
    let len = r.read_varint()? as usize;

    // Empty arrays carry no element bytes — skip element-type inspection entirely.
    // This also covers `Array(Nothing)`, which is normalized to `Array(Int8)` in
    // the header parser; an empty-length prefix reaches this branch with any
    // declared element type.
    if len == 0 {
        return Ok(Vec::new());
    }

    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        let (v, from) = read_int_any(r, inner)?;
        out.push(narrow_to_i8(v, from)?);
    }
    Ok(out)
}

/// Extracts the element type from an `Array(T)`, erroring with context if `t` is not an Array.
pub fn array_elem<'a>(t: &'a DataTypeNode, ctx: &str) -> CodecResult<&'a DataTypeNode> {
    match t {
        DataTypeNode::Array(inner) => Ok(inner),
        other => Err(CodecError::TypeMismatch(format!(
            "{ctx}: expected Array(...), got {other}"
        ))),
    }
}

/// Extracts tuple field types, asserting the expected arity.
pub fn tuple_fields<'a>(
    t: &'a DataTypeNode,
    expected: usize,
    ctx: &str,
) -> CodecResult<&'a [DataTypeNode]> {
    match t {
        DataTypeNode::Tuple(fields) if fields.len() == expected => Ok(fields),
        DataTypeNode::Tuple(fields) => Err(CodecError::TypeMismatch(format!(
            "{ctx}: Tuple arity {} != expected {}",
            fields.len(),
            expected
        ))),
        other => Err(CodecError::TypeMismatch(format!(
            "{ctx}: expected Tuple, got {other}"
        ))),
    }
}

/// Reads a UUID from a `UUID` column.
pub fn read_uuid<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<uuid::Uuid> {
    match t {
        DataTypeNode::UUID => r.read_uuid(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected UUID, got {other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::rowbinary::RowBinaryWrite;
    use std::io::Write;

    #[test]
    fn u8_accepts_int64_wire() {
        let mut buf = Vec::new();
        buf.write_all(&42i64.to_le_bytes()).unwrap();
        let mut slice = buf.as_slice();
        let got = read_u8_col(&mut slice, &DataTypeNode::Int64).unwrap();
        assert_eq!(got, 42);
    }

    #[test]
    fn u8_rejects_int64_out_of_range() {
        let mut buf = Vec::new();
        buf.write_all(&300i64.to_le_bytes()).unwrap();
        let mut slice = buf.as_slice();
        let err = read_u8_col(&mut slice, &DataTypeNode::Int64).unwrap_err();
        assert!(matches!(err, CodecError::IntOutOfRange { to: "UInt8", .. }));
    }

    #[test]
    fn u64_rejects_negative() {
        let mut buf = Vec::new();
        buf.write_all(&(-1i64).to_le_bytes()).unwrap();
        let mut slice = buf.as_slice();
        let err = read_u64_col(&mut slice, &DataTypeNode::Int64).unwrap_err();
        assert!(matches!(
            err,
            CodecError::IntOutOfRange { to: "UInt64", .. }
        ));
    }

    #[test]
    fn array_i8_accepts_array_int64() {
        let mut buf = Vec::new();
        buf.write_varint(3).unwrap();
        buf.write_all(&1i64.to_le_bytes()).unwrap();
        buf.write_all(&(-2i64).to_le_bytes()).unwrap();
        buf.write_all(&3i64.to_le_bytes()).unwrap();
        let mut slice = buf.as_slice();
        let got = read_array_i8(
            &mut slice,
            &DataTypeNode::Array(Box::new(DataTypeNode::Int64)),
        )
        .unwrap();
        assert_eq!(got, vec![1, -2, 3]);
    }

    // ClickHouse infers Array(UInt8) for small positive literals like `[0,0,0]`.
    // The narrow path must accept that.
    #[test]
    fn array_i8_accepts_array_uint8() {
        let mut buf = Vec::new();
        buf.write_varint(3).unwrap();
        buf.write_u8(0).unwrap();
        buf.write_u8(5).unwrap();
        buf.write_u8(127).unwrap();
        let mut slice = buf.as_slice();
        let got = read_array_i8(
            &mut slice,
            &DataTypeNode::Array(Box::new(DataTypeNode::UInt8)),
        )
        .unwrap();
        assert_eq!(got, vec![0, 5, 127]);
    }

    #[test]
    fn read_int_peels_low_cardinality() {
        let mut buf = Vec::new();
        buf.write_u64_le(42).unwrap();
        let mut slice = buf.as_slice();
        let t = DataTypeNode::LowCardinality(Box::new(DataTypeNode::UInt64));
        let got = read_u64_col(&mut slice, &t).unwrap();
        assert_eq!(got, 42);
    }

    // Empty array: no element bytes follow, so element-type is never inspected.
    // Covers the Array(Nothing) path post-normalization in header.rs.
    #[test]
    fn array_i8_empty_skips_element_type_check() {
        let mut buf = Vec::new();
        buf.write_varint(0).unwrap();
        let mut slice = buf.as_slice();
        let got = read_array_i8(
            &mut slice,
            &DataTypeNode::Array(Box::new(DataTypeNode::Int64)),
        )
        .unwrap();
        assert!(got.is_empty());
    }

    #[test]
    fn nullable_string_accepts_plain_string() {
        let mut buf = Vec::new();
        buf.write_bytes(b"hello").unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_string(&mut slice, &DataTypeNode::String).unwrap();
        assert_eq!(got, b"hello");
    }

    #[test]
    fn nullable_f64_accepts_plain_float64() {
        let mut buf = Vec::new();
        buf.write_f64_le(1.5).unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_f64(&mut slice, &DataTypeNode::Float64).unwrap();
        assert_eq!(got, 1.5);
    }
}
