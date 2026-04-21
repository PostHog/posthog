use std::io::{BufRead, Write};

use uuid::Uuid;

use crate::codec::msgpack;
use crate::codec::CodecResult;
use crate::io::column::{
    read_array_i8, read_array_len, read_nullable_f64, read_string, read_tuple_arity, read_u64_col,
    read_u8_col, read_uuid,
};
use crate::io::propval::{read_propval, read_propval_array, write_propval};
use crate::trends::{Args, Event, ResultStruct};
use crate::types::BreakdownShape;

// Argument order on the wire (per XML aggregate_funnel_trends / _array_trends /
// _cohort_trends):
//   0 from_step, 1 to_step, 2 num_steps, 3 conversion_window_limit,
//   4 breakdown_attribution_type, 5 funnel_order_type, 6 prop_vals, 7 value.
pub fn read_args<R: BufRead>(r: &mut R, shape: BreakdownShape) -> CodecResult<Args> {
    let from_step = read_u8_col(r)? as usize;
    let to_step = read_u8_col(r)? as usize;
    let num_steps = read_u8_col(r)? as usize;
    let conversion_window_limit = read_u64_col(r)?;
    let breakdown_attribution_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let funnel_order_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let prop_vals = read_propval_array(r, shape)?;

    let value_len = read_array_len(r)?;
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

/// Auto-detect breakdown shape from first prop_vals element (or first event
/// breakdown slot). Mirrors `steps_io::read_args_auto`.
pub fn read_args_auto<R: BufRead>(r: &mut R) -> CodecResult<(Args, BreakdownShape)> {
    let from_step = read_u8_col(r)? as usize;
    let to_step = read_u8_col(r)? as usize;
    let num_steps = read_u8_col(r)? as usize;
    let conversion_window_limit = read_u64_col(r)?;
    let breakdown_attribution_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let funnel_order_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;

    let prop_len = read_array_len(r)?;
    let shape = if prop_len > 0 {
        detect_shape_from_next(r)?
    } else {
        BreakdownShape::NullableString
    };
    let mut prop_vals = Vec::with_capacity(prop_len);
    for _ in 0..prop_len {
        prop_vals.push(read_propval(r, shape)?);
    }

    let value_len = read_array_len(r)?;
    let mut value = Vec::with_capacity(value_len);
    let mut refined_shape = shape;
    for i in 0..value_len {
        if i == 0 && prop_len == 0 {
            // Trends event tuple: (ts, interval_start, uuid, breakdown, steps).
            read_tuple_arity(r, 5, "event")?;
            let timestamp = read_nullable_f64(r)?;
            let interval_start = read_u64_col(r)?;
            let uuid = read_uuid(r)?;
            refined_shape = detect_shape_from_next(r)?;
            let breakdown = read_propval(r, refined_shape)?;
            let steps = read_array_i8(r)?;
            value.push(Event {
                timestamp,
                interval_start,
                uuid,
                breakdown,
                steps,
            });
        } else {
            value.push(read_event(r, refined_shape)?);
        }
    }

    Ok((
        Args {
            from_step,
            to_step,
            num_steps,
            conversion_window_limit,
            breakdown_attribution_type,
            funnel_order_type,
            prop_vals,
            value,
        },
        refined_shape,
    ))
}

fn detect_shape_from_next<R: BufRead>(r: &mut R) -> CodecResult<BreakdownShape> {
    let m =
        crate::codec::msgpack::peek_marker(r)?.ok_or(crate::codec::CodecError::UnexpectedEof)?;
    crate::io::propval::shape_from_marker(m).ok_or_else(|| {
        crate::codec::CodecError::TypeMismatch(format!(
            "cannot infer breakdown shape from marker {m:?}"
        ))
    })
}

fn read_event<R: BufRead>(r: &mut R, shape: BreakdownShape) -> CodecResult<Event> {
    read_tuple_arity(r, 5, "event")?;
    let timestamp = read_nullable_f64(r)?;
    let interval_start = read_u64_col(r)?;
    let uuid = read_uuid(r)?;
    let breakdown = read_propval(r, shape)?;
    let steps = read_array_i8(r)?;
    Ok(Event {
        timestamp,
        interval_start,
        uuid,
        breakdown,
        steps,
    })
}

pub fn write_results<W: Write>(
    w: &mut W,
    results: &[ResultStruct],
    shape: BreakdownShape,
) -> CodecResult<()> {
    msgpack::write_array_len(w, results.len() as u32)?;
    for r in results {
        // Trends result tuple: (UInt64, Int8, <breakdown>, UUID)
        msgpack::write_array_len(w, 4)?;
        msgpack::write_uint(w, r.0)?;
        msgpack::write_sint(w, r.1 as i64)?;
        write_propval(w, &r.2, shape)?;
        msgpack::write_uuid(w, r.3)?;
    }
    let _ = std::any::type_name::<Uuid>();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::msgpack::{
        write_array_len, write_bin, write_f64, write_sint, write_uint, write_uuid,
    };
    use crate::types::{Bytes, PropVal};
    use std::io::Cursor;

    #[test]
    fn trends_args_roundtrip_array_string() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let mut buf = Vec::new();
        write_uint(&mut buf, 0).unwrap(); // from_step
        write_uint(&mut buf, 2).unwrap(); // to_step
        write_uint(&mut buf, 3).unwrap(); // num_steps
        write_uint(&mut buf, 86_400).unwrap(); // conversion_window_limit
        write_bin(&mut buf, b"step_1").unwrap();
        write_bin(&mut buf, b"unordered").unwrap();
        // prop_vals: Array(Array(String)) length 1
        write_array_len(&mut buf, 1).unwrap();
        write_array_len(&mut buf, 2).unwrap();
        write_bin(&mut buf, b"a").unwrap();
        write_bin(&mut buf, b"b").unwrap();
        // value: length 1
        write_array_len(&mut buf, 1).unwrap();
        write_array_len(&mut buf, 5).unwrap(); // tuple arity
        write_f64(&mut buf, 1.5).unwrap();
        write_uint(&mut buf, 1_700_000_000).unwrap();
        write_uuid(&mut buf, uuid).unwrap();
        // breakdown = Array(String) of ["a", "b"]
        write_array_len(&mut buf, 2).unwrap();
        write_bin(&mut buf, b"a").unwrap();
        write_bin(&mut buf, b"b").unwrap();
        // steps = [1, 2, 3]
        write_array_len(&mut buf, 3).unwrap();
        write_sint(&mut buf, 1).unwrap();
        write_sint(&mut buf, 2).unwrap();
        write_sint(&mut buf, 3).unwrap();

        let mut cur = Cursor::new(buf);
        let args = read_args(&mut cur, BreakdownShape::ArrayString).unwrap();
        assert_eq!(args.from_step, 0);
        assert_eq!(args.to_step, 2);
        assert_eq!(args.num_steps, 3);
        assert_eq!(args.conversion_window_limit, 86_400);
        assert_eq!(args.prop_vals.len(), 1);
        assert_eq!(
            args.prop_vals[0],
            PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())])
        );
        assert_eq!(args.value.len(), 1);
        assert_eq!(args.value[0].timestamp, 1.5);
        assert_eq!(args.value[0].interval_start, 1_700_000_000);
        assert_eq!(args.value[0].uuid, uuid);
    }
}
