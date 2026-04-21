use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{array_elem, read_bytes_col, read_int_col};
use crate::types::{BreakdownShape, Bytes, PropVal};

// Reads one breakdown value. Shape is detected once per chunk (see `detect_shape`)
// from the prop_vals column type and reused everywhere — one binary serves all 3
// XML variants (nullable_string / array_string / u64) without a CLI flag.
pub fn read_propval<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    t: &DataTypeNode,
) -> CodecResult<PropVal> {
    match shape {
        BreakdownShape::NullableString => Ok(PropVal::String(Bytes(read_bytes_col(r, t)?))),
        BreakdownShape::ArrayString => {
            let inner = array_elem(t, "breakdown")?;
            let len = r.read_varint()? as usize;
            let mut out = Vec::with_capacity(len);
            for _ in 0..len {
                out.push(Bytes(read_bytes_col(r, inner)?));
            }
            Ok(PropVal::Vec(out))
        }
        BreakdownShape::U64 => Ok(PropVal::Int(read_int_col(r, t)? as u64)),
    }
}

pub fn read_propval_array<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    t: &DataTypeNode,
) -> CodecResult<Vec<PropVal>> {
    let inner = array_elem(t, "prop_vals")?;
    let len = r.read_varint()? as usize;
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        out.push(read_propval(r, shape, inner)?);
    }
    Ok(out)
}

pub fn write_propval<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    p: &PropVal,
    shape: BreakdownShape,
) -> CodecResult<()> {
    match (shape, p) {
        (BreakdownShape::NullableString, PropVal::String(b)) => {
            w.write_u8(0)?; // non-null
            w.write_bytes(&b.0)
        }
        (BreakdownShape::ArrayString, PropVal::Vec(v)) => {
            w.write_array(v, |w, b| w.write_bytes(&b.0))
        }
        (BreakdownShape::U64, PropVal::Int(n)) => w.write_u64_le(*n),
        (shape, p) => {
            unreachable!("PropVal {p:?} does not match detected BreakdownShape {shape:?}")
        }
    }
}

/// Output-header type for the breakdown slot; must stay in sync with `write_propval`.
pub fn shape_output_type(shape: BreakdownShape) -> DataTypeNode {
    match shape {
        BreakdownShape::NullableString => DataTypeNode::Nullable(Box::new(DataTypeNode::String)),
        BreakdownShape::ArrayString => DataTypeNode::Array(Box::new(DataTypeNode::String)),
        BreakdownShape::U64 => DataTypeNode::UInt64,
    }
}

/// Picks the breakdown shape from the prop_vals element type on the wire.
/// Peels LowCardinality and Nullable so the shape matches the underlying kind:
///   U64           — any integer element (cohort ids)
///   ArrayString   — nested Array(String) (element Nullable/LC irrelevant)
///   NullableString — anything string-like
pub fn detect_shape(prop_vals_type: &DataTypeNode) -> CodecResult<BreakdownShape> {
    let inner = array_elem(prop_vals_type, "detect_shape on prop_vals")?;
    let peeled = peel_shape_wrappers(inner);
    match peeled {
        DataTypeNode::UInt8
        | DataTypeNode::UInt16
        | DataTypeNode::UInt32
        | DataTypeNode::UInt64
        | DataTypeNode::Int8
        | DataTypeNode::Int16
        | DataTypeNode::Int32
        | DataTypeNode::Int64 => Ok(BreakdownShape::U64),
        DataTypeNode::Array(_) => Ok(BreakdownShape::ArrayString),
        DataTypeNode::String | DataTypeNode::FixedString(_) => Ok(BreakdownShape::NullableString),
        other => Err(CodecError::TypeMismatch(format!(
            "prop_vals: unsupported element type {other}"
        ))),
    }
}

fn peel_shape_wrappers(t: &DataTypeNode) -> &DataTypeNode {
    let t = t.remove_low_cardinality();
    match t {
        DataTypeNode::Nullable(inner) => inner.remove_low_cardinality(),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn array_of(t: DataTypeNode) -> DataTypeNode {
        DataTypeNode::Array(Box::new(t))
    }

    fn nullable_string() -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(DataTypeNode::String))
    }

    // Shape is picked from the prop_vals element type. Wrappers (Nullable, LC)
    // and narrower int widths all collapse to the expected shape — HogQL doesn't
    // always emit the exact type declared in the XML.
    #[rstest]
    #[case::nullable_string(array_of(nullable_string()), BreakdownShape::NullableString)]
    #[case::plain_string(array_of(DataTypeNode::String), BreakdownShape::NullableString)]
    #[case::uint64(array_of(DataTypeNode::UInt64), BreakdownShape::U64)]
    #[case::int64(array_of(DataTypeNode::Int64), BreakdownShape::U64)]
    #[case::uint32(array_of(DataTypeNode::UInt32), BreakdownShape::U64)]
    #[case::nested_array(array_of(array_of(DataTypeNode::String)), BreakdownShape::ArrayString)]
    fn detects_shape(#[case] prop_vals_type: DataTypeNode, #[case] expected: BreakdownShape) {
        assert_eq!(detect_shape(&prop_vals_type).unwrap(), expected);
    }

    #[test]
    fn nullable_string_reads_nullable_wire() {
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(b"hi").unwrap();
        let got = read_propval(
            &mut buf.as_slice(),
            BreakdownShape::NullableString,
            &nullable_string(),
        )
        .unwrap();
        assert_eq!(got, PropVal::String(Bytes(b"hi".to_vec())));
    }

    #[test]
    fn u64_reads_uint64_wire() {
        let mut buf = Vec::new();
        buf.write_u64_le(1209600).unwrap();
        let got = read_propval(
            &mut buf.as_slice(),
            BreakdownShape::U64,
            &DataTypeNode::UInt64,
        )
        .unwrap();
        assert_eq!(got, PropVal::Int(1209600));
    }

    // CH `String` is byte-typed — a breakdown key with non-UTF-8 bytes must
    // survive round-trip intact rather than being lossy-converted.
    #[test]
    fn non_utf8_bytes_survive() {
        let bad = vec![0xff, 0xfe, 0x00, 0x80];
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(&bad).unwrap();
        let got = read_propval(
            &mut buf.as_slice(),
            BreakdownShape::NullableString,
            &nullable_string(),
        )
        .unwrap();
        assert_eq!(got, PropVal::String(Bytes(bad)));
    }

    // NULL breakdown → empty string bucket (matches JSONEachRow and what
    // funnel_trends returns as "" breakdown_value).
    #[test]
    fn null_breakdown_maps_to_empty_string() {
        let got = read_propval(
            &mut [1u8].as_slice(),
            BreakdownShape::NullableString,
            &nullable_string(),
        )
        .unwrap();
        assert_eq!(got, PropVal::String(Bytes(Vec::new())));
    }
}
