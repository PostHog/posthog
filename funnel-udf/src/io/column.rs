// Permissive leaves, strict structure. Three things to know about what ClickHouse
// puts on the wire:
//
//   1. Integer widths are whatever the source expression evaluated to, NOT the
//      UDF's XML-declared arg type. A UInt8 slot routinely arrives as Int64
//      because HogQL emits integer literals as Int64. We widen through i128
//      and narrow with bounds checks.
//
//   2. Any slot can arrive Nullable-wrapped even if the XML declares it
//      non-nullable — ClickHouse inherits Nullable from any nullable sub-expression
//      in the source. Every reader peels Nullable transparently; a null value
//      maps to that type's zero/empty (the `""` breakdown bucket, `0` int,
//      empty array, nil UUID, `0.0` timestamp).
//
//   3. LowCardinality wrappers are a storage hint with no wire-level effect;
//      we peel them too (and accept LowCardinality(Nullable(T))).
//
// Tuple arity and column count are checked exactly — a mismatch there is a
// broken UDF contract, not a type-coercion candidate.

use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::RowBinaryRead;
use crate::codec::{CodecError, CodecResult};

/// Peels `Nullable` (and `LowCardinality`) off `t`. If the result is `Nullable(inner)`,
/// consumes one null-marker byte from `r`: returns `Ok(None)` on null, `Ok(Some(inner))`
/// on non-null. If `t` isn't Nullable, returns `Ok(Some(t))` without reading.
/// `LowCardinality(Nullable(T))` and `Nullable(LowCardinality(T))` both collapse
/// to `Some(T)` / `None` as expected.
fn peel_nullable<'a, R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &'a DataTypeNode,
) -> CodecResult<Option<&'a DataTypeNode>> {
    let t = t.remove_low_cardinality();
    if let DataTypeNode::Nullable(inner) = t {
        match r.read_u8()? {
            0 => Ok(Some(inner.remove_low_cardinality())),
            1 => Ok(None),
            b => Err(CodecError::InvalidNullMarker(b)),
        }
    } else {
        Ok(Some(t))
    }
}

fn read_int_raw<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<(i128, &'static str)> {
    match t {
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
    let Some(inner) = peel_nullable(r, t)? else {
        return Ok(0);
    };
    let (v, from) = read_int_raw(r, inner)?;
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
    let Some(inner) = peel_nullable(r, t)? else {
        return Ok(0);
    };
    let (v, from) = read_int_raw(r, inner)?;
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

/// `Float64` / `Nullable(Float64)` / `Float32` / `Nullable(Float32)`. A null
/// timestamp coerces to 0.0, matching the permissive policy elsewhere — an
/// entity with a truly null timestamp will sort anomalously, but the UDF
/// shouldn't take down the query for it.
pub fn read_nullable_f64<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<f64> {
    let Some(inner) = peel_nullable(r, t)? else {
        return Ok(0.0);
    };
    match inner {
        DataTypeNode::Float64 => r.read_f64_le(),
        DataTypeNode::Float32 => {
            let mut b = [0u8; 4];
            r.read_exact(&mut b)?;
            Ok(f32::from_le_bytes(b) as f64)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected Float64 or Float32, got {other}"
        ))),
    }
}

/// Reads `String` / `FixedString(N)` / `Nullable(String)` / `LowCardinality(...)`.
/// Null maps to empty bytes.
pub fn read_string<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<Vec<u8>> {
    let Some(inner) = peel_nullable(r, t)? else {
        return Ok(Vec::new());
    };
    match inner {
        DataTypeNode::String => r.read_bytes(),
        DataTypeNode::FixedString(n) => {
            let mut buf = vec![0u8; *n];
            r.read_exact(&mut buf)?;
            Ok(buf)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected String or FixedString, got {other}"
        ))),
    }
}

/// Explicit alias for breakdown slots. Identical to `read_string` now that null
/// handling is uniform; kept as a named call site for call-site readability.
pub fn read_nullable_string<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<u8>> {
    read_string(r, t)
}

/// Reads an `Array(T)` where elements narrow to Int8. Accepts any int-family
/// element type, `Array(Nothing)` (empty only), and `Nullable(...)` at either
/// the array or element level — null elements map to 0.
pub fn read_array_i8<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<i8>> {
    let Some(inner_of_nullable) = peel_nullable(r, t)? else {
        return Ok(Vec::new());
    };
    let elem_t = array_elem(inner_of_nullable, "Array(Int8)")?;
    let len = r.read_varint()? as usize;

    // Empty: no element bytes follow, so the element type is never inspected
    // (covers `Array(Nothing)` normalized to `Array(Int8)` in the header parser).
    if len == 0 {
        return Ok(Vec::new());
    }

    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        let Some(elem_unwrapped) = peel_nullable(r, elem_t)? else {
            out.push(0);
            continue;
        };
        let (v, from) = read_int_raw(r, elem_unwrapped)?;
        out.push(narrow_to_i8(v, from)?);
    }
    Ok(out)
}

/// Returns the element type of `Array(T)` (after peeling `LowCardinality`).
/// Errors if `t` isn't an array.
pub fn array_elem<'a>(t: &'a DataTypeNode, ctx: &str) -> CodecResult<&'a DataTypeNode> {
    match t.remove_low_cardinality() {
        DataTypeNode::Array(inner) => Ok(inner),
        other => Err(CodecError::TypeMismatch(format!(
            "{ctx}: expected Array(...), got {other}"
        ))),
    }
}

pub fn tuple_fields<'a>(
    t: &'a DataTypeNode,
    expected: usize,
    ctx: &str,
) -> CodecResult<&'a [DataTypeNode]> {
    match t.remove_low_cardinality() {
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

/// `UUID` / `Nullable(UUID)`. Null maps to the nil UUID.
pub fn read_uuid<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<uuid::Uuid> {
    let Some(inner) = peel_nullable(r, t)? else {
        return Ok(uuid::Uuid::nil());
    };
    match inner {
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

    fn nullable(inner: DataTypeNode) -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(inner))
    }

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
    fn u64_null_maps_to_zero() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap(); // null marker
        let mut slice = buf.as_slice();
        let got = read_u64_col(&mut slice, &nullable(DataTypeNode::UInt64)).unwrap();
        assert_eq!(got, 0);
    }

    #[test]
    fn u8_null_maps_to_zero() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let got = read_u8_col(&mut slice, &nullable(DataTypeNode::UInt8)).unwrap();
        assert_eq!(got, 0);
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

    // Empty array: no element bytes follow, so the element type is never inspected.
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

    // Array itself wrapped Nullable — null array = empty vec.
    #[test]
    fn array_i8_null_array_is_empty() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let t = nullable(DataTypeNode::Array(Box::new(DataTypeNode::Int8)));
        let got = read_array_i8(&mut slice, &t).unwrap();
        assert!(got.is_empty());
    }

    // Per-element Nullable — null element = 0.
    #[test]
    fn array_i8_null_elements_map_to_zero() {
        let mut buf = Vec::new();
        buf.write_varint(3).unwrap();
        buf.write_u8(0).unwrap(); // non-null marker
        buf.write_i8(7).unwrap();
        buf.write_u8(1).unwrap(); // null
        buf.write_u8(0).unwrap();
        buf.write_i8(-3).unwrap();
        let mut slice = buf.as_slice();
        let t = DataTypeNode::Array(Box::new(nullable(DataTypeNode::Int8)));
        let got = read_array_i8(&mut slice, &t).unwrap();
        assert_eq!(got, vec![7, 0, -3]);
    }

    #[test]
    fn nullable_string_accepts_plain_string() {
        let mut buf = Vec::new();
        buf.write_bytes(b"hello").unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_string(&mut slice, &DataTypeNode::String).unwrap();
        assert_eq!(got, b"hello");
    }

    // Null breakdown → empty string bucket.
    #[test]
    fn nullable_string_null_maps_to_empty() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_string(&mut slice, &nullable(DataTypeNode::String)).unwrap();
        assert!(got.is_empty());
    }

    // LowCardinality(Nullable(String)) is what CH picks for low-cardinality
    // string breakdowns. The wire still carries a null-marker + bytes; peel both.
    #[test]
    fn string_peels_lc_of_nullable() {
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(b"en").unwrap();
        let mut slice = buf.as_slice();
        let t = DataTypeNode::LowCardinality(Box::new(nullable(DataTypeNode::String)));
        let got = read_string(&mut slice, &t).unwrap();
        assert_eq!(got, b"en");
    }

    #[test]
    fn nullable_f64_accepts_plain_float64() {
        let mut buf = Vec::new();
        buf.write_f64_le(1.5).unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_f64(&mut slice, &DataTypeNode::Float64).unwrap();
        assert_eq!(got, 1.5);
    }

    #[test]
    fn nullable_f64_null_maps_to_zero() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let got = read_nullable_f64(&mut slice, &nullable(DataTypeNode::Float64)).unwrap();
        assert_eq!(got, 0.0);
    }

    #[test]
    fn uuid_null_maps_to_nil() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let got = read_uuid(&mut slice, &nullable(DataTypeNode::UUID)).unwrap();
        assert_eq!(got, uuid::Uuid::nil());
    }
}
