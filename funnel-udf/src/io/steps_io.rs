use std::io::{BufRead, Write};

use uuid::Uuid;

use crate::codec::msgpack;
use crate::codec::CodecResult;
use crate::io::column::{
    read_array_i8, read_array_len, read_nullable_f64, read_string, read_tuple_arity, read_u32_col,
    read_u64_col, read_u8_col, read_uuid,
};
use crate::io::propval::{read_propval, read_propval_array, write_propval};
use crate::steps::{Args, Event, Result as StepsResult};
use crate::types::BreakdownShape;

// Argument order on the wire (per XML aggregate_funnel / _cohort / _array):
//   0 num_steps, 1 conversion_window_limit, 2 breakdown_attribution_type,
//   3 funnel_order_type, 4 prop_vals, 5 optional_steps, 6 value.
pub fn read_args<R: BufRead>(r: &mut R, shape: BreakdownShape) -> CodecResult<Args> {
    let num_steps = read_u8_col(r)? as usize;
    let conversion_window_limit = read_u64_col(r)?;
    let breakdown_attribution_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let funnel_order_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let prop_vals = read_propval_array(r, shape)?;
    let optional_steps = read_array_i8(r)?;

    let value_len = read_array_len(r)?;
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

/// Like `read_args`, but auto-detects the breakdown shape from the first
/// prop_vals element (or from the first event's breakdown if prop_vals is
/// empty). Used for the first row of a chunk; subsequent rows can reuse the
/// detected shape via `read_args`.
pub fn read_args_auto<R: BufRead>(r: &mut R) -> CodecResult<(Args, BreakdownShape)> {
    let num_steps = read_u8_col(r)? as usize;
    let conversion_window_limit = read_u64_col(r)?;
    let breakdown_attribution_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;
    let funnel_order_type =
        String::from_utf8(read_string(r)?).map_err(|_| crate::codec::CodecError::InvalidUtf8)?;

    // Peek first prop_vals element's marker to decide shape.
    let prop_len = read_array_len(r)?;
    let shape = if prop_len > 0 {
        detect_shape_from_next(r)?
    } else {
        BreakdownShape::NullableString // will refine below if events give us a signal
    };
    let mut prop_vals = Vec::with_capacity(prop_len);
    for _ in 0..prop_len {
        prop_vals.push(read_propval(r, shape)?);
    }

    let optional_steps = read_array_i8(r)?;

    let value_len = read_array_len(r)?;
    let mut value = Vec::with_capacity(value_len);
    let mut refined_shape = shape;
    for i in 0..value_len {
        if i == 0 && prop_len == 0 {
            // Use the event's breakdown field to refine shape. Event tuple
            // layout: (ts, uuid, breakdown, steps). Skip ts + uuid first.
            read_tuple_arity(r, 4, "event")?;
            let timestamp = read_nullable_f64(r)?;
            let uuid = read_uuid(r)?;
            refined_shape = detect_shape_from_next(r)?;
            let breakdown = read_propval(r, refined_shape)?;
            let steps = read_array_i8(r)?;
            value.push(Event {
                timestamp,
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
            num_steps,
            conversion_window_limit,
            breakdown_attribution_type,
            funnel_order_type,
            prop_vals,
            optional_steps,
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
    read_tuple_arity(r, 4, "event")?;
    let timestamp = read_nullable_f64(r)?;
    let uuid = read_uuid(r)?;
    let breakdown = read_propval(r, shape)?;
    let steps = read_array_i8(r)?;
    Ok(Event {
        timestamp,
        uuid,
        breakdown,
        steps,
    })
}

/// Write the result row for one entity: one `Array(Tuple(...))` value per
/// UDF invocation. The outer array length is the number of funnel results.
pub fn write_results<W: Write>(
    w: &mut W,
    results: &[StepsResult],
    shape: BreakdownShape,
) -> CodecResult<()> {
    msgpack::write_array_len(w, results.len() as u32)?;
    for r in results {
        // Result tuple: (Int8, <breakdown>, Array(Float64), Array(Array(UUID)), UInt32)
        msgpack::write_array_len(w, 5)?;
        msgpack::write_sint(w, r.0 as i64)?;
        write_propval(w, &r.1, shape)?;
        msgpack::write_array_len(w, r.2.len() as u32)?;
        for t in &r.2 {
            msgpack::write_f64(w, *t)?;
        }
        msgpack::write_array_len(w, r.3.len() as u32)?;
        for row in &r.3 {
            msgpack::write_array_len(w, row.len() as u32)?;
            for u in row {
                msgpack::write_uuid(w, *u)?;
            }
        }
        msgpack::write_uint(w, r.4 as u64)?;
    }
    // Silence unused import warnings in builds that strip tests
    let _ = std::any::type_name::<Uuid>();
    let _ = read_u32_col::<std::io::Cursor<&[u8]>>;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::msgpack::{
        write_array_len, write_bin, write_f64, write_nil, write_sint, write_uint, write_uuid,
    };
    use crate::types::{Bytes, PropVal};
    use std::io::Cursor;

    #[test]
    fn args_roundtrip_nullable_string() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let mut buf = Vec::new();
        write_uint(&mut buf, 3).unwrap(); // num_steps
        write_uint(&mut buf, 3600).unwrap(); // conversion_window_limit
        write_bin(&mut buf, b"first_touch").unwrap(); // breakdown_attribution_type
        write_bin(&mut buf, b"ordered").unwrap(); // funnel_order_type
                                                  // prop_vals: Array(Nullable(String)) of length 1
        write_array_len(&mut buf, 1).unwrap();
        write_bin(&mut buf, b"en").unwrap();
        // optional_steps: Array(Int8), empty
        write_array_len(&mut buf, 0).unwrap();
        // value: Array(Tuple(ts, uuid, breakdown, steps)) of length 1
        write_array_len(&mut buf, 1).unwrap();
        write_array_len(&mut buf, 4).unwrap(); // tuple arity
        write_f64(&mut buf, 1.5).unwrap(); // timestamp
        write_uuid(&mut buf, uuid).unwrap();
        write_bin(&mut buf, b"en").unwrap(); // breakdown
        write_array_len(&mut buf, 1).unwrap(); // steps
        write_sint(&mut buf, 1).unwrap();

        let mut cur = Cursor::new(buf);
        let args = read_args(&mut cur, BreakdownShape::NullableString).unwrap();
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
    fn nil_breakdown_errors_when_non_null_expected() {
        // prop_vals = [nil] under NullableString shape: the invariant says we
        // never see true nils here. Make sure we fail loudly.
        let mut buf = Vec::new();
        write_uint(&mut buf, 1).unwrap();
        write_uint(&mut buf, 1).unwrap();
        write_bin(&mut buf, b"a").unwrap();
        write_bin(&mut buf, b"a").unwrap();
        write_array_len(&mut buf, 1).unwrap();
        write_nil(&mut buf).unwrap(); // nil element
        let mut cur = Cursor::new(buf);
        let err = read_args(&mut cur, BreakdownShape::NullableString).unwrap_err();
        assert!(matches!(err, crate::codec::CodecError::UnexpectedNull));
    }
}
