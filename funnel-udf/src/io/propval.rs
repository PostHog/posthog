use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{array_elem, read_nullable_string, read_string, read_u64_col};
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
        BreakdownShape::NullableString => Ok(PropVal::String(Bytes(read_nullable_string(r, t)?))),
        BreakdownShape::ArrayString => {
            let inner = array_elem(t, "breakdown")?;
            let len = r.read_varint()? as usize;
            let mut out = Vec::with_capacity(len);
            for _ in 0..len {
                out.push(Bytes(read_string(r, inner)?));
            }
            Ok(PropVal::Vec(out))
        }
        BreakdownShape::U64 => Ok(PropVal::Int(read_u64_col(r, t)?)),
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
        _ => Err(CodecError::ShapeMismatch),
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
/// Each shape accepts a family of near-variants (see column.rs for why):
///   U64           — any integer element (cohort ids)
///   ArrayString   — Array(String) with or without LowCardinality wrap
///   NullableString — Nullable(String) or plain String
pub fn detect_shape(prop_vals_type: &DataTypeNode) -> CodecResult<BreakdownShape> {
    let inner = array_elem(prop_vals_type, "detect_shape on prop_vals")?;
    let peeled = match inner {
        DataTypeNode::LowCardinality(x) => x.as_ref(),
        other => other,
    };
    match peeled {
        DataTypeNode::UInt8
        | DataTypeNode::UInt16
        | DataTypeNode::UInt32
        | DataTypeNode::UInt64
        | DataTypeNode::Int8
        | DataTypeNode::Int16
        | DataTypeNode::Int32
        | DataTypeNode::Int64 => Ok(BreakdownShape::U64),
        DataTypeNode::Array(el)
            if matches!(**el, DataTypeNode::String | DataTypeNode::LowCardinality(_)) =>
        {
            Ok(BreakdownShape::ArrayString)
        }
        DataTypeNode::Nullable(el) if matches!(**el, DataTypeNode::String) => {
            Ok(BreakdownShape::NullableString)
        }
        DataTypeNode::String => Ok(BreakdownShape::NullableString),
        other => Err(CodecError::TypeMismatch(format!(
            "prop_vals: unsupported element type {other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn nullable_string() -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(DataTypeNode::String))
    }

    #[test]
    fn shape_detection() {
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(nullable_string()))).unwrap(),
            BreakdownShape::NullableString
        );
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::UInt64))).unwrap(),
            BreakdownShape::U64
        );
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::Array(
                Box::new(DataTypeNode::String)
            ))))
            .unwrap(),
            BreakdownShape::ArrayString
        );
    }

    // ClickHouse strips the Nullable wrapper when the source expression is
    // statically non-null — Array(String) without Nullable must still detect.
    #[test]
    fn shape_detection_accepts_plain_string_as_nullable() {
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::String))).unwrap(),
            BreakdownShape::NullableString
        );
    }

    // HogQL defaults integer literals to Int64, so a cohort-id breakdown can
    // arrive as Int64 even though the XML declares Array(UInt64). All widths map.
    #[test]
    fn shape_detection_accepts_narrower_int_widths() {
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::Int64))).unwrap(),
            BreakdownShape::U64
        );
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::UInt32))).unwrap(),
            BreakdownShape::U64
        );
    }

    #[test]
    fn nullable_string_reads_nullable_wire() {
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(b"hi").unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(
            &mut slice,
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
        let mut slice = buf.as_slice();
        let got = read_propval(&mut slice, BreakdownShape::U64, &DataTypeNode::UInt64).unwrap();
        assert_eq!(got, PropVal::Int(1209600));
    }

    #[test]
    fn non_utf8_bytes_survive() {
        let bad = vec![0xff, 0xfe, 0x00, 0x80];
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_bytes(&bad).unwrap();
        let mut slice = buf.as_slice();
        let got = read_propval(
            &mut slice,
            BreakdownShape::NullableString,
            &nullable_string(),
        )
        .unwrap();
        assert_eq!(got, PropVal::String(Bytes(bad)));
    }

    #[test]
    fn unexpected_null_errors() {
        let mut buf = Vec::new();
        buf.write_u8(1).unwrap();
        let mut slice = buf.as_slice();
        let err = read_propval(
            &mut slice,
            BreakdownShape::NullableString,
            &nullable_string(),
        )
        .unwrap_err();
        assert!(matches!(err, CodecError::UnexpectedNull));
    }
}
