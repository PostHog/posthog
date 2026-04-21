use clickhouse_types::DataTypeNode;

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{array_elem, read_nullable_string, read_string, read_u64_col};
use crate::types::{BreakdownShape, Bytes, PropVal};

// Reads a single breakdown value — at either a `prop_vals` element position or
// a per-event tuple position. `t` is the actual column/field type from the
// block header. The declared `BreakdownShape` still governs which PropVal
// variant we produce.
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

/// Reads the entire `prop_vals` column: `Array(<shape>)`.
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

// Writer side is unchanged — we emit the schema we declare in the output
// block header, so this is self-consistent.
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

/// The `DataTypeNode` we emit in output block headers for a given shape.
/// Must match write_propval's wire format exactly.
pub fn shape_output_type(shape: BreakdownShape) -> DataTypeNode {
    match shape {
        BreakdownShape::NullableString => DataTypeNode::Nullable(Box::new(DataTypeNode::String)),
        BreakdownShape::ArrayString => DataTypeNode::Array(Box::new(DataTypeNode::String)),
        BreakdownShape::U64 => DataTypeNode::UInt64,
    }
}

/// Detects the intended `BreakdownShape` from the actual `prop_vals` column type
/// on the wire. We're permissive about wire types (see io/column.rs for the
/// rationale) so each shape accepts a family of near-variants:
///   - U64: any integer element (cohort ids fit in UInt64; narrower widths are fine)
///   - ArrayString: nested `Array(String)` (with or without LowCardinality)
///   - NullableString: Nullable(String) or plain String (treat non-nullable as always-non-null)
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

    #[test]
    fn shape_detection_accepts_plain_string_as_nullable() {
        // HogQL-generated queries don't always wrap string breakdowns in Nullable.
        // Plain `Array(String)` should map to the NullableString shape and be
        // treated as always-non-null on read.
        assert_eq!(
            detect_shape(&DataTypeNode::Array(Box::new(DataTypeNode::String))).unwrap(),
            BreakdownShape::NullableString
        );
    }

    #[test]
    fn shape_detection_accepts_narrower_int_widths() {
        // Cohort breakdowns may arrive as Int64 (HogQL's default for int literals)
        // or other widths; they all map to the U64 shape.
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
