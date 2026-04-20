use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::propval::{read_propval, read_propval_array, write_propval};
use crate::trends::{Args, Event, ResultStruct};
use crate::types::BreakdownShape;

// Wire shape (per XML aggregate_funnel_trends / aggregate_funnel_array_trends / aggregate_funnel_cohort_trends):
//   UInt8 from_step
//   UInt8 to_step
//   UInt8 num_steps
//   UInt64 conversion_window_limit
//   String breakdown_attribution_type
//   String funnel_order_type
//   Array(<prop shape>) prop_vals
//   Array(Tuple(Nullable(Float64), UInt64, UUID, <breakdown shape>, Array(Int8))) value
pub fn read_args<R: RowBinaryRead + ?Sized>(r: &mut R, shape: BreakdownShape) -> CodecResult<Args> {
    let from_step = r.read_u8()? as usize;
    let to_step = r.read_u8()? as usize;
    let num_steps = r.read_u8()? as usize;
    let conversion_window_limit = r.read_u64_le()?;
    let breakdown_attribution_type = r.read_string()?;
    let funnel_order_type = r.read_string()?;
    let prop_vals = read_propval_array(r, shape)?;
    let value_len = r.read_varint()? as usize;
    let mut value = Vec::with_capacity(value_len);
    for _ in 0..value_len {
        value.push(read_event(r, shape)?);
    }
    Ok(Args {
        from_step,
        to_step,
        num_steps,
        conversion_window_limit,
        breakdown_attribution_type,
        funnel_order_type,
        prop_vals,
        value,
    })
}

fn read_event<R: RowBinaryRead + ?Sized>(r: &mut R, shape: BreakdownShape) -> CodecResult<Event> {
    let timestamp = r
        .read_nullable(|r| r.read_f64_le())?
        .ok_or(CodecError::UnexpectedNull)?;
    let interval_start = r.read_u64_le()?;
    let uuid = r.read_uuid()?;
    let breakdown = read_propval(r, shape)?;
    let steps = r.read_array(|r| r.read_i8())?;
    Ok(Event {
        timestamp,
        interval_start,
        uuid,
        breakdown,
        steps,
    })
}

// Wire shape of the return:
//   Array(Tuple(UInt64 interval_start, Int8 success, <breakdown shape>, UUID))
pub fn write_results<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    results: &[ResultStruct],
    shape: BreakdownShape,
) -> CodecResult<()> {
    w.write_varint(results.len() as u64)?;
    for r in results {
        w.write_u64_le(r.0)?;
        w.write_i8(r.1)?;
        write_propval(w, &r.2, shape)?;
        w.write_uuid(r.3)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{Bytes, PropVal};
    use uuid::Uuid;

    #[test]
    fn args_roundtrip_array_string_shape() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let original = Args {
            from_step: 0,
            to_step: 2,
            num_steps: 3,
            conversion_window_limit: 86_400,
            breakdown_attribution_type: "step_1".into(),
            funnel_order_type: "unordered".into(),
            prop_vals: vec![PropVal::Vec(vec![
                Bytes(b"a".to_vec()),
                Bytes(b"b".to_vec()),
            ])],
            value: vec![Event {
                timestamp: 1.5,
                interval_start: 1_700_000_000,
                uuid,
                breakdown: PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())]),
                steps: vec![1, 2, 3],
            }],
        };

        let mut buf = Vec::new();
        buf.write_u8(original.from_step as u8).unwrap();
        buf.write_u8(original.to_step as u8).unwrap();
        buf.write_u8(original.num_steps as u8).unwrap();
        buf.write_u64_le(original.conversion_window_limit).unwrap();
        buf.write_string(&original.breakdown_attribution_type)
            .unwrap();
        buf.write_string(&original.funnel_order_type).unwrap();
        buf.write_varint(original.prop_vals.len() as u64).unwrap();
        for p in &original.prop_vals {
            write_propval(&mut buf, p, BreakdownShape::ArrayString).unwrap();
        }
        buf.write_varint(original.value.len() as u64).unwrap();
        for e in &original.value {
            buf.write_u8(0).unwrap();
            buf.write_f64_le(e.timestamp).unwrap();
            buf.write_u64_le(e.interval_start).unwrap();
            buf.write_uuid(e.uuid).unwrap();
            write_propval(&mut buf, &e.breakdown, BreakdownShape::ArrayString).unwrap();
            buf.write_array(&e.steps, |w, v| w.write_i8(*v)).unwrap();
        }

        let mut slice = buf.as_slice();
        let round = read_args(&mut slice, BreakdownShape::ArrayString).unwrap();
        assert_eq!(round.from_step, original.from_step);
        assert_eq!(round.to_step, original.to_step);
        assert_eq!(round.num_steps, original.num_steps);
        assert_eq!(
            round.conversion_window_limit,
            original.conversion_window_limit
        );
        assert_eq!(
            round.breakdown_attribution_type,
            original.breakdown_attribution_type
        );
        assert_eq!(round.funnel_order_type, original.funnel_order_type);
        assert_eq!(round.prop_vals, original.prop_vals);
        assert_eq!(round.value.len(), 1);
        assert_eq!(round.value[0].interval_start, 1_700_000_000);
        assert_eq!(round.value[0].timestamp, 1.5);
        assert_eq!(round.value[0].uuid, uuid);
        assert_eq!(
            round.value[0].breakdown,
            PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())])
        );
        assert_eq!(round.value[0].steps, vec![1, 2, 3]);
    }

    #[test]
    fn results_roundtrip_u64_shape() {
        let uuid = Uuid::parse_str("00000000-0000-0000-0000-000000000001").unwrap();
        let results = vec![
            ResultStruct(1_700_000_000, 1, PropVal::Int(42), uuid),
            ResultStruct(1_700_086_400, -1, PropVal::Int(42), uuid),
        ];
        let mut buf = Vec::new();
        write_results(&mut buf, &results, BreakdownShape::U64).unwrap();

        let mut slice = buf.as_slice();
        let len = slice.read_varint().unwrap();
        assert_eq!(len, 2);
        assert_eq!(slice.read_u64_le().unwrap(), 1_700_000_000);
        assert_eq!(slice.read_i8().unwrap(), 1);
        assert_eq!(
            read_propval(&mut slice, BreakdownShape::U64).unwrap(),
            PropVal::Int(42)
        );
        assert_eq!(slice.read_uuid().unwrap(), uuid);
    }
}
