use clickhouse_types::{Column, DataTypeNode};

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{
    array_elem, read_bytes_col, read_float_col, read_int_array_i8, read_int_col, read_uuid_col,
    tuple_fields,
};
use crate::io::propval::{read_propval, read_propval_array, shape_output_type, write_propval};
use crate::steps::{Args, Event, Result as StepsResult};
use crate::types::BreakdownShape;

// Column layout per XML aggregate_funnel{,_cohort,_array}:
//   0 UInt8    num_steps
//   1 UInt64   conversion_window_limit
//   2 String   breakdown_attribution_type
//   3 String   funnel_order_type
//   4 Array(<breakdown shape>)                                              prop_vals
//   5 Array(Int8)                                                           optional_steps
//   6 Array(Tuple(Nullable(Float64), UUID, <breakdown shape>, Array(Int8))) value
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

    let num_steps = read_int_col(r, &columns[0].data_type)? as usize;
    let conversion_window_limit = read_int_col(r, &columns[1].data_type)? as u64;
    let breakdown_attribution_type =
        String::from_utf8_lossy(&read_bytes_col(r, &columns[2].data_type)?).into_owned();
    let funnel_order_type =
        String::from_utf8_lossy(&read_bytes_col(r, &columns[3].data_type)?).into_owned();
    let prop_vals = read_propval_array(r, shape, &columns[4].data_type)?;
    let optional_steps = read_int_array_i8(r, &columns[5].data_type)?;

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
    let timestamp = read_float_col(r, &fields[0])?;
    let uuid = read_uuid_col(r, &fields[1])?;
    let breakdown = read_propval(r, shape, &fields[2])?;
    let steps = read_int_array_i8(r, &fields[3])?;
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

    fn nullable_string() -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(DataTypeNode::String))
    }

    fn nullable_float64() -> DataTypeNode {
        DataTypeNode::Nullable(Box::new(DataTypeNode::Float64))
    }

    fn nullable_string_columns() -> Vec<Column> {
        vec![
            Column::new("num_steps".into(), DataTypeNode::UInt8),
            Column::new("conversion_window_limit".into(), DataTypeNode::UInt64),
            Column::new("breakdown_attribution_type".into(), DataTypeNode::String),
            Column::new("funnel_order_type".into(), DataTypeNode::String),
            Column::new(
                "prop_vals".into(),
                DataTypeNode::Array(Box::new(nullable_string())),
            ),
            Column::new(
                "optional_steps".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
            ),
            Column::new(
                "value".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                    nullable_float64(),
                    DataTypeNode::UUID,
                    nullable_string(),
                    DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
                ]))),
            ),
        ]
    }

    #[test]
    fn args_roundtrip_strict_wire() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let mut buf = Vec::new();

        buf.write_u8(3).unwrap();
        buf.write_u64_le(3600).unwrap();
        buf.write_bytes(b"first_touch").unwrap();
        buf.write_bytes(b"ordered").unwrap();
        buf.write_varint(1).unwrap();
        buf.write_u8(0).unwrap(); // not-null marker
        buf.write_bytes(b"en").unwrap();
        buf.write_varint(0).unwrap();
        buf.write_varint(1).unwrap();
        buf.write_u8(0).unwrap(); // not-null marker for timestamp
        buf.write_f64_le(1.5).unwrap();
        buf.write_uuid(uuid).unwrap();
        buf.write_u8(0).unwrap(); // not-null marker for breakdown
        buf.write_bytes(b"en").unwrap();
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

    // Int widths are accepted interchangeably in int slots, but a non-int
    // source (like String) in an int slot has to fail cleanly.
    #[test]
    fn args_rejects_wrong_wire_type() {
        let mut cols = nullable_string_columns();
        cols[1] = Column::new("conversion_window_limit".into(), DataTypeNode::String);
        let err =
            read_args(&mut [0u8].as_slice(), BreakdownShape::NullableString, &cols).unwrap_err();
        assert!(matches!(err, CodecError::TypeMismatch(_)));
    }

    #[test]
    fn schema_len_mismatch_errors_cleanly() {
        let cols = vec![Column::new("a".into(), DataTypeNode::UInt8)];
        let err =
            read_args(&mut [0u8].as_slice(), BreakdownShape::NullableString, &cols).unwrap_err();
        assert!(matches!(err, CodecError::SchemaLen { got: 1, want: 7 }));
    }
}
