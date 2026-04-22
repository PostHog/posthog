// Permissive leaves, strict structure.
//
// What ClickHouse actually puts on the wire doesn't always match the XML-declared
// UDF arg type. Three realities:
//
//   1. Integer widths come from the source expression, not the XML. ClickHouse
//      statically promotes arithmetic result types to guarantee no overflow
//      over the operands' full ranges (UInt8 * UInt8 -> UInt16, and so on up),
//      so a slot the XML calls Int8/UInt8 often arrives wider. We read whatever
//      width the block header declares, widen to i64, and let the per-slot
//      caller truncating-cast to its target.
//
//   2. Any slot can arrive Nullable-wrapped, even if declared non-nullable —
//      CH inherits Nullable from any nullable sub-expression upstream. Every
//      reader peels Nullable; a null maps to that type's zero/empty (`""`
//      breakdown, `0` int, empty array, nil UUID, `0.0` timestamp).
//
//   3. LowCardinality is a storage hint with no wire effect; peel it too,
//      including LowCardinality(Nullable(T)) and Nullable(LowCardinality(T)).
//
// Tuple arity and column count are checked exactly — a mismatch there is a
// broken UDF contract, not a coercion candidate.

use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::RowBinaryRead;
use crate::codec::{CodecError, CodecResult};

/// Reads a column that may or may not be `Nullable`, peeling `LowCardinality`
/// at either level. On null, returns `null_default` without consuming any payload
/// bytes. On non-null, calls `read_payload` with the inner (non-Nullable, non-LC)
/// type. This is the one place the permissive-null policy lives — every `_col`
/// reader below goes through here.
fn read_or_null<R: RowBinaryRead + ?Sized, T, F>(
    r: &mut R,
    t: &DataTypeNode,
    null_default: T,
    read_payload: F,
) -> CodecResult<T>
where
    F: FnOnce(&mut R, &DataTypeNode) -> CodecResult<T>,
{
    let t = t.remove_low_cardinality();
    let inner = match t {
        DataTypeNode::Nullable(inner) => match r.read_u8()? {
            0 => inner.remove_low_cardinality(),
            1 => return Ok(null_default),
            b => {
                return Err(CodecError::CorruptWire(format!(
                    "invalid Nullable marker byte: {b}"
                )))
            }
        },
        other => other,
    };
    read_payload(r, inner)
}

/// Reads one integer, widening every width to `i64`. Unsigned source widths
/// zero-extend; signed widths sign-extend.
fn read_int<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<i64> {
    Ok(match t {
        DataTypeNode::UInt8 | DataTypeNode::Bool => u8::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::UInt16 => u16::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::UInt32 => u32::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::UInt64 => u64::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::Int8 => i8::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::Int16 => i16::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::Int32 => i32::from_le_bytes(r.read_le()?) as i64,
        DataTypeNode::Int64 => i64::from_le_bytes(r.read_le()?),
        other => {
            return Err(CodecError::TypeMismatch(format!(
                "expected integer type, got {other}"
            )))
        }
    })
}

/// Reads any int-family column (any width, any sign), returns `i64`. Callers
/// cast to their target type (`as u8`, `as usize`, `as u64`). The `i64 ↔ u64`
/// cast preserves bit patterns, so a UInt64 above `i64::MAX` round-trips intact.
pub fn read_int_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<i64> {
    read_or_null(r, t, 0, read_int)
}

/// `Float64` / `Float32`, with or without Nullable / LowCardinality. A null
/// timestamp coerces to 0.0 — an entity with a truly null timestamp will sort
/// anomalously, but the UDF shouldn't take down the query for it.
pub fn read_float_col<R: RowBinaryRead + ?Sized>(r: &mut R, t: &DataTypeNode) -> CodecResult<f64> {
    read_or_null(r, t, 0.0, |r, inner| match inner {
        DataTypeNode::Float64 => r.read_f64_le(),
        DataTypeNode::Float32 => Ok(f32::from_le_bytes(r.read_le()?) as f64),
        other => Err(CodecError::TypeMismatch(format!(
            "expected Float64 or Float32, got {other}"
        ))),
    })
}

/// `String` / `FixedString(N)`, with or without Nullable / LowCardinality.
/// CH `String` is byte-typed; we return bytes without UTF-8 validation.
/// Null maps to empty bytes.
pub fn read_bytes_col<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<u8>> {
    read_or_null(r, t, Vec::new(), |r, inner| match inner {
        DataTypeNode::String => r.read_bytes(),
        DataTypeNode::FixedString(n) => {
            let mut buf = vec![0u8; *n];
            r.read_exact(&mut buf)?;
            Ok(buf)
        }
        other => Err(CodecError::TypeMismatch(format!(
            "expected String or FixedString, got {other}"
        ))),
    })
}

/// Reads an int-family array and narrows each element to `i8`. Accepts any int
/// element width and Nullable at either the array or element level — null array
/// → empty vec, null element → 0. (The header parser normalizes `Array(Nothing)`
/// to `Array(Int8)` with length 0, so the element type is always int-family.)
pub fn read_int_array_i8<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<Vec<i8>> {
    read_or_null(r, t, Vec::new(), |r, inner| {
        let elem_t = array_elem(inner, "Array(Int8)")?;
        let len = r.read_varint()? as usize;
        let mut out = Vec::with_capacity(len);
        for _ in 0..len {
            out.push(read_or_null(r, elem_t, 0, read_int)? as i8);
        }
        Ok(out)
    })
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

/// `UUID`, with or without Nullable / LowCardinality. Null maps to the nil UUID.
pub fn read_uuid_col<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    t: &DataTypeNode,
) -> CodecResult<uuid::Uuid> {
    read_or_null(r, t, uuid::Uuid::nil(), |r, inner| match inner {
        DataTypeNode::UUID => r.read_uuid(),
        other => Err(CodecError::TypeMismatch(format!(
            "expected UUID, got {other}"
        ))),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::rowbinary::RowBinaryWrite;
    use std::io::Write;

    use rstest::rstest;

    fn nullable(inner: DataTypeNode) -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(inner))
    }

    fn lc(inner: DataTypeNode) -> DataTypeNode {
        DataTypeNode::LowCardinality(Box::new(inner))
    }

    // int_col: any source width widens to i64 cleanly
    #[rstest]
    #[case::int64_wire(DataTypeNode::Int64, 42i64.to_le_bytes().to_vec())]
    #[case::uint32_wire(DataTypeNode::UInt32, 42u32.to_le_bytes().to_vec())]
    #[case::uint8_wire(DataTypeNode::UInt8, vec![42])]
    #[case::lc_uint64(lc(DataTypeNode::UInt64), 42u64.to_le_bytes().to_vec())]
    fn int_col_widens_any_width(#[case] t: DataTypeNode, #[case] wire: Vec<u8>) {
        assert_eq!(read_int_col(&mut wire.as_slice(), &t).unwrap(), 42);
    }

    // All _col readers route through read_or_null, so one null test covers the policy.
    #[test]
    fn int_col_null_maps_to_zero() {
        assert_eq!(
            read_int_col(&mut [1u8].as_slice(), &nullable(DataTypeNode::UInt64)).unwrap(),
            0
        );
    }

    // LowCardinality(Nullable(String)) — the shape CH picks for LC string
    // breakdowns. Peels both wrappers; consumes the null marker + payload.
    #[test]
    fn bytes_col_peels_lc_of_nullable() {
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(b"en").unwrap();
        let t = lc(nullable(DataTypeNode::String));
        assert_eq!(read_bytes_col(&mut buf.as_slice(), &t).unwrap(), b"en");
    }

    // int_array_i8: narrows any element int width to i8
    #[rstest]
    #[case::array_int64(
        DataTypeNode::Array(Box::new(DataTypeNode::Int64)),
        {
            let mut b = Vec::new();
            b.write_varint(3).unwrap();
            for v in [1i64, -2, 3] { b.write_all(&v.to_le_bytes()).unwrap(); }
            b
        },
        vec![1i8, -2, 3]
    )]
    // CH infers Array(UInt8) for small positive literals like `[0, 5, 127]`.
    #[case::array_uint8(
        DataTypeNode::Array(Box::new(DataTypeNode::UInt8)),
        {
            let mut b = Vec::new();
            b.write_varint(3).unwrap();
            for v in [0u8, 5, 127] { b.write_u8(v).unwrap(); }
            b
        },
        vec![0i8, 5, 127]
    )]
    fn int_array_i8_narrows_any_element_width(
        #[case] t: DataTypeNode,
        #[case] wire: Vec<u8>,
        #[case] expected: Vec<i8>,
    ) {
        assert_eq!(
            read_int_array_i8(&mut wire.as_slice(), &t).unwrap(),
            expected
        );
    }

    // Nullable can wrap the whole array (null → empty) or each element (null → 0)
    #[test]
    fn int_array_i8_null_array_is_empty() {
        let t = nullable(DataTypeNode::Array(Box::new(DataTypeNode::Int8)));
        assert!(read_int_array_i8(&mut [1u8].as_slice(), &t)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn int_array_i8_null_element_is_zero() {
        let mut buf = Vec::new();
        buf.write_varint(3).unwrap();
        buf.write_u8(0).unwrap(); // non-null
        buf.write_i8(7).unwrap();
        buf.write_u8(1).unwrap(); // null
        buf.write_u8(0).unwrap(); // non-null
        buf.write_i8(-3).unwrap();
        let t = DataTypeNode::Array(Box::new(nullable(DataTypeNode::Int8)));
        assert_eq!(
            read_int_array_i8(&mut buf.as_slice(), &t).unwrap(),
            vec![7, 0, -3]
        );
    }
}
