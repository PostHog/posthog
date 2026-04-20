use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::propval::{read_propval, read_propval_array, write_propval};
use crate::steps::{Args, Event, Result as StepsResult};
use crate::types::BreakdownShape;

// Wire shape (per XML aggregate_funnel / aggregate_funnel_array / aggregate_funnel_cohort):
//   UInt8 num_steps
//   UInt64 conversion_window_limit
//   String breakdown_attribution_type
//   String funnel_order_type
//   Array(<prop shape>) prop_vals
//   Array(Int8) optional_steps
//   Array(Tuple(Nullable(Float64), UUID, <breakdown shape>, Array(Int8))) value
pub fn read_args<R: RowBinaryRead + ?Sized>(r: &mut R, shape: BreakdownShape) -> CodecResult<Args> {
    let num_steps = r.read_u8()? as usize;
    let conversion_window_limit = r.read_u64_le()?;
    let breakdown_attribution_type = r.read_string()?;
    let funnel_order_type = r.read_string()?;
    let prop_vals = read_propval_array(r, shape)?;
    let optional_steps = r.read_array(|r| r.read_i8())?;
    let value_len = r.read_varint()? as usize;
    let mut value = Vec::with_capacity(value_len);
    for _ in 0..value_len {
        value.push(read_event(r, shape)?);
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

fn read_event<R: RowBinaryRead + ?Sized>(r: &mut R, shape: BreakdownShape) -> CodecResult<Event> {
    let timestamp = r
        .read_nullable(|r| r.read_f64_le())?
        .ok_or(CodecError::UnexpectedNull)?;
    let uuid = r.read_uuid()?;
    let breakdown = read_propval(r, shape)?;
    let steps = r.read_array(|r| r.read_i8())?;
    Ok(Event {
        timestamp,
        uuid,
        breakdown,
        steps,
    })
}

// Wire shape of the return:
//   Array(Tuple(Int8, <breakdown shape>, Array(Float64), Array(Array(UUID)), UInt32))
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

    #[test]
    fn args_roundtrip_nullable_string_shape() {
        let original = Args {
            num_steps: 3,
            conversion_window_limit: 3600,
            breakdown_attribution_type: "first_touch".into(),
            funnel_order_type: "ordered".into(),
            prop_vals: vec![
                PropVal::String(Bytes(b"en".to_vec())),
                PropVal::String(Bytes(b"fr".to_vec())),
            ],
            optional_steps: vec![2],
            value: vec![
                Event {
                    timestamp: 1.5,
                    uuid: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
                    breakdown: PropVal::String(Bytes(b"en".to_vec())),
                    steps: vec![1, 2],
                },
                Event {
                    timestamp: 2.5,
                    uuid: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440001").unwrap(),
                    breakdown: PropVal::String(Bytes(b"fr".to_vec())),
                    steps: vec![1],
                },
            ],
        };

        let mut buf = Vec::new();
        // Mimic what the caller would do: write args by hand in the same shape
        // to exercise read_args via the round-trip fixture.
        buf.push(original.num_steps as u8);
        buf.extend_from_slice(&original.conversion_window_limit.to_le_bytes());
        buf.write_string(&original.breakdown_attribution_type)
            .unwrap();
        buf.write_string(&original.funnel_order_type).unwrap();
        buf.write_varint(original.prop_vals.len() as u64).unwrap();
        for p in &original.prop_vals {
            write_propval(&mut buf, p, BreakdownShape::NullableString).unwrap();
        }
        buf.write_array(&original.optional_steps, |w, v| w.write_i8(*v))
            .unwrap();
        buf.write_varint(original.value.len() as u64).unwrap();
        for e in &original.value {
            buf.write_u8(0).unwrap(); // Nullable(Float64) non-null marker
            buf.write_f64_le(e.timestamp).unwrap();
            buf.write_uuid(e.uuid).unwrap();
            write_propval(&mut buf, &e.breakdown, BreakdownShape::NullableString).unwrap();
            buf.write_array(&e.steps, |w, v| w.write_i8(*v)).unwrap();
        }

        let mut slice = buf.as_slice();
        let round = read_args(&mut slice, BreakdownShape::NullableString).unwrap();

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
        assert_eq!(round.optional_steps, original.optional_steps);
        assert_eq!(round.value.len(), original.value.len());
        for (a, b) in round.value.iter().zip(original.value.iter()) {
            assert_eq!(a.timestamp, b.timestamp);
            assert_eq!(a.uuid, b.uuid);
            assert_eq!(a.breakdown, b.breakdown);
            assert_eq!(a.steps, b.steps);
        }
    }

    #[test]
    fn results_roundtrip_nullable_string_shape() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let results = vec![
            StepsResult(
                2,
                PropVal::String(Bytes(b"en".to_vec())),
                vec![1.5, 3.0],
                vec![vec![uuid], vec![uuid], vec![uuid]],
                7,
            ),
            StepsResult(-1, PropVal::String(Bytes(Vec::new())), vec![], vec![], 0),
        ];
        let mut buf = Vec::new();
        write_results(&mut buf, &results, BreakdownShape::NullableString).unwrap();

        // Read it back by hand
        let mut slice = buf.as_slice();
        let len = slice.read_varint().unwrap();
        assert_eq!(len, 2);
        let r0_step = slice.read_i8().unwrap();
        assert_eq!(r0_step, 2);
        let r0_prop = read_propval(&mut slice, BreakdownShape::NullableString).unwrap();
        assert_eq!(r0_prop, PropVal::String(Bytes(b"en".to_vec())));
    }
}
