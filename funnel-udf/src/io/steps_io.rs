use clickhouse_types::{Column, DataTypeNode};

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{
    array_elem, read_array_i8, read_f64_nonnull, read_string_bytes_nonnull, read_uint_as_u64,
    read_uuid, tuple_fields,
};
use crate::io::propval::{read_propval, read_propval_array, shape_output_type, write_propval};
use crate::steps::{Args, Event, Result as StepsResult};
use crate::types::BreakdownShape;

// Column layout (per XML aggregate_funnel / aggregate_funnel_cohort / aggregate_funnel_array):
//   0  UInt8    num_steps
//   1  UInt64   conversion_window_limit
//   2  String   breakdown_attribution_type
//   3  String   funnel_order_type
//   4  Array(<breakdown shape>)   prop_vals
//   5  Array(Int8)                optional_steps
//   6  Array(Tuple(Nullable(Float64), UUID, <breakdown shape>, Array(Int8)))  value
//
// Reader is tolerant of the shape actually arriving on the wire (UInt32 vs
// UInt64, plain String vs Nullable(String), etc.) — see column.rs.
const COLUMN_COUNT: usize = 7;

pub fn read_args<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    columns: &[Column],
) -> CodecResult<Args> {
    if columns.len() != COLUMN_COUNT {
        return Err(CodecError::SchemaLen {
            got: columns.len(),
            want: COLUMN_COUNT,
        });
    }

    let num_steps = read_uint_as_u64(r, &columns[0].data_type)? as usize;
    let conversion_window_limit = read_uint_as_u64(r, &columns[1].data_type)?;
    let breakdown_attribution_type =
        String::from_utf8(read_string_bytes_nonnull(r, &columns[2].data_type)?)
            .map_err(|_| CodecError::InvalidUtf8)?;
    let funnel_order_type = String::from_utf8(read_string_bytes_nonnull(r, &columns[3].data_type)?)
        .map_err(|_| CodecError::InvalidUtf8)?;
    let prop_vals = read_propval_array(r, shape, &columns[4].data_type)?;
    let optional_steps = read_array_i8(r, &columns[5].data_type)?;

    let value_elem = array_elem(&columns[6].data_type, "value")?;
    let event_fields = tuple_fields(value_elem, 4, "value tuple")?;

    let value_len = r.read_varint()? as usize;
    let mut value = Vec::with_capacity(value_len);
    for _ in 0..value_len {
        value.push(read_event(r, shape, event_fields)?);
    }

    Ok(Args {
        num_steps,
        conversion_window_limit,
        breakdown_attribution_type,
        funnel_order_type,
        prop_vals,
        optional_steps,
        value,
    })
}

fn read_event<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    fields: &[DataTypeNode],
) -> CodecResult<Event> {
    let timestamp = read_f64_nonnull(r, &fields[0])?;
    let uuid = read_uuid(r, &fields[1])?;
    let breakdown = read_propval(r, shape, &fields[2])?;
    let steps = read_array_i8(r, &fields[3])?;
    Ok(Event {
        timestamp,
        uuid,
        breakdown,
        steps,
    })
}

/// Block header we emit on the output side. `shape` picks the breakdown slot's type.
pub fn output_columns(shape: BreakdownShape) -> Vec<Column> {
    let inner = DataTypeNode::Tuple(vec![
        DataTypeNode::Int8,
        shape_output_type(shape),
        DataTypeNode::Array(Box::new(DataTypeNode::Float64)),
        DataTypeNode::Array(Box::new(DataTypeNode::Array(Box::new(DataTypeNode::UUID)))),
        DataTypeNode::UInt32,
    ]);
    vec![Column::new(
        "result".into(),
        DataTypeNode::Array(Box::new(inner)),
    )]
}

pub fn write_results<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    results: &[StepsResult],
    shape: BreakdownShape,
) -> CodecResult<()> {
    w.write_varint(results.len() as u64)?;
    for r in results {
        w.write_i8(r.0)?;
        write_propval(w, &r.1, shape)?;
        w.write_array(&r.2, |w, t| w.write_f64_le(*t))?;
        w.write_array(&r.3, |w, row| w.write_array(row, |w, u| w.write_uuid(*u)))?;
        w.write_u32_le(r.4)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{Bytes, PropVal};
    use uuid::Uuid;

    fn nullable_string_columns() -> Vec<Column> {
        vec![
            Column::new("num_steps".into(), DataTypeNode::UInt8),
            // Real-world: SQL passes UInt32 literal even though XML says UInt64.
            Column::new("conversion_window_limit".into(), DataTypeNode::UInt32),
            Column::new("breakdown_attribution_type".into(), DataTypeNode::String),
            Column::new("funnel_order_type".into(), DataTypeNode::String),
            Column::new(
                "prop_vals".into(),
                // Real-world: `ifNull(...)` makes inner String, not Nullable(String).
                DataTypeNode::Array(Box::new(DataTypeNode::String)),
            ),
            Column::new(
                "optional_steps".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
            ),
            Column::new(
                "value".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                    DataTypeNode::Float64, // not Nullable
                    DataTypeNode::UUID,
                    DataTypeNode::String, // not Nullable
                    DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
                ]))),
            ),
        ]
    }

    #[test]
    fn args_roundtrip_tolerates_nonnullable_wire() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let mut buf = Vec::new();

        buf.write_u8(3).unwrap();
        buf.write_u32_le(3600).unwrap(); // UInt32, not UInt64!
        buf.write_bytes(b"first_touch").unwrap();
        buf.write_bytes(b"ordered").unwrap();
        buf.write_varint(1).unwrap();
        buf.write_bytes(b"en").unwrap();
        buf.write_varint(0).unwrap();
        buf.write_varint(1).unwrap();
        buf.write_f64_le(1.5).unwrap(); // plain Float64
        buf.write_uuid(uuid).unwrap();
        buf.write_bytes(b"en").unwrap(); // plain String
        buf.write_varint(1).unwrap();
        buf.write_i8(1).unwrap();

        let mut slice = buf.as_slice();
        let args = read_args(
            &mut slice,
            BreakdownShape::NullableString,
            &nullable_string_columns(),
        )
        .unwrap();
        assert_eq!(args.num_steps, 3);
        assert_eq!(args.conversion_window_limit, 3600);
        assert_eq!(args.breakdown_attribution_type, "first_touch");
        assert_eq!(args.funnel_order_type, "ordered");
        assert_eq!(args.prop_vals.len(), 1);
        assert_eq!(args.prop_vals[0], PropVal::String(Bytes(b"en".to_vec())));
        assert_eq!(args.value.len(), 1);
        assert_eq!(args.value[0].timestamp, 1.5);
        assert_eq!(args.value[0].uuid, uuid);
        assert_eq!(
            args.value[0].breakdown,
            PropVal::String(Bytes(b"en".to_vec()))
        );
        assert_eq!(args.value[0].steps, vec![1]);
    }

    #[test]
    fn schema_len_mismatch_errors_cleanly() {
        let cols = vec![Column::new("a".into(), DataTypeNode::UInt8)];
        let buf = [0u8; 1];
        let mut slice = buf.as_slice();
        let err = match read_args(&mut slice, BreakdownShape::NullableString, &cols) {
            Err(e) => e,
            Ok(_) => panic!("expected SchemaLen error"),
        };
        assert!(matches!(err, CodecError::SchemaLen { got: 1, want: 7 }));
    }
}
