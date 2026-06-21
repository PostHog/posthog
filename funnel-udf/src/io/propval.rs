use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{read_array_col, read_bytes_col, read_int_col};
use crate::types::{BreakdownShape, Bytes, PropVal};

// Reads one breakdown value. Shape is pinned at process startup by the
// `--variant` CLI arg — each XML <function> block has its own executable_pool,
// so the variant never changes for the lifetime of this process.
pub fn read_propval<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    t: &DataTypeNode,
) -> CodecResult<PropVal> {
    match shape {
        BreakdownShape::NullableString => Ok(PropVal::String(Bytes(read_bytes_col(r, t)?))),
        BreakdownShape::ArrayString => {
            let out = read_array_col(r, t, "breakdown", |r, inner| {
                Ok(Bytes(read_bytes_col(r, inner)?))
            })?;
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
    read_array_col(r, t, "prop_vals", |r, inner| read_propval(r, shape, inner))
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
        (shape, p) => Err(CodecError::CorruptWire(format!(
            "PropVal {p:?} does not match BreakdownShape {shape:?} (invariant violation)"
        ))),
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::rowbinary::RowBinaryWrite;
    use rstest::rstest;

    fn nullable_string() -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(DataTypeNode::String))
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

    fn array_string() -> DataTypeNode {
        DataTypeNode::Array(Box::new(DataTypeNode::String))
    }

    fn nullable(inner: DataTypeNode) -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(inner))
    }

    // The array-breakdown reader must handle every `Nullable`/`LowCardinality`
    // shape a multi-property breakdown can inherit upstream, rather than crash
    // the process. Each case exercises a genuinely distinct path:
    //   - `strict_wire`: bare `Array(String)`, no null markers.
    //   - `nullable_wrapped_non_null`: a `Nullable(Array(String))` whose value is
    //     present — the array-level null marker must be peeled (the regression).
    //   - `null_array`: a `Nullable(Array(String))` that is null → empty bucket.
    //   - `null_element`: `Array(Nullable(String))` with a null element → "".
    #[rstest]
    #[case::strict_wire(
        array_string(),
        b"\x02\x02us\x03pro".to_vec(),
        vec![Bytes(b"us".to_vec()), Bytes(b"pro".to_vec())]
    )]
    #[case::nullable_wrapped_non_null(
        nullable(array_string()),
        b"\x00\x02\x02us\x03pro".to_vec(),
        vec![Bytes(b"us".to_vec()), Bytes(b"pro".to_vec())]
    )]
    #[case::null_array(nullable(array_string()), b"\x01".to_vec(), vec![])]
    #[case::null_element(
        DataTypeNode::Array(Box::new(nullable_string())),
        b"\x02\x00\x02us\x01".to_vec(),
        vec![Bytes(b"us".to_vec()), Bytes(Vec::new())]
    )]
    fn array_breakdown_peels_nullable(
        #[case] t: DataTypeNode,
        #[case] wire: Vec<u8>,
        #[case] expected: Vec<Bytes>,
    ) {
        let got = read_propval(&mut wire.as_slice(), BreakdownShape::ArrayString, &t).unwrap();
        assert_eq!(got, PropVal::Vec(expected));
    }
}
