use super::*;
use clickhouse_types::{Column, DataTypeNode};

use crate::codec::chunk::write_chunk_header;
use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::io::propval::read_propval;
use crate::types::BreakdownShape;
use std::io::Cursor;
use uuid::Uuid;

// Test fixture: block header with the exact XML-declared steps shapes.
fn write_steps_header(buf: &mut Vec<u8>) {
    let nullable_string = DataTypeNode::Nullable(Box::new(DataTypeNode::String));
    let nullable_f64 = DataTypeNode::Nullable(Box::new(DataTypeNode::Float64));
    let cols = vec![
        Column::new("num_steps".into(), DataTypeNode::UInt8),
        Column::new("conversion_window_limit".into(), DataTypeNode::UInt64),
        Column::new("breakdown_attribution_type".into(), DataTypeNode::String),
        Column::new("funnel_order_type".into(), DataTypeNode::String),
        Column::new(
            "prop_vals".into(),
            DataTypeNode::Array(Box::new(nullable_string.clone())),
        ),
        Column::new(
            "optional_steps".into(),
            DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
        ),
        Column::new(
            "value".into(),
            DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                nullable_f64,
                DataTypeNode::UUID,
                nullable_string,
                DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
            ]))),
        ),
    ];
    write_block_header(buf, &cols).unwrap();
}

#[test]
fn rowbinary_steps_round_trip_strict_wire() {
    let uuid0 = Uuid::parse_str("00000000-0000-0000-0000-000000000001").unwrap();
    let uuid1 = Uuid::parse_str("00000000-0000-0000-0000-000000000002").unwrap();
    let uuid2 = Uuid::parse_str("00000000-0000-0000-0000-000000000003").unwrap();

    let mut input_buf = Vec::new();
    write_chunk_header(&mut input_buf, 1).unwrap();
    write_steps_header(&mut input_buf);

    input_buf.write_u8(3).unwrap();
    input_buf.write_u64_le(3600).unwrap();
    input_buf.write_bytes(b"first_touch").unwrap();
    input_buf.write_bytes(b"ordered").unwrap();
    input_buf.write_varint(1).unwrap();
    input_buf.write_u8(0).unwrap(); // prop_vals[0] not-null marker
    input_buf.write_bytes(b"en").unwrap();
    input_buf.write_varint(0).unwrap();
    input_buf.write_varint(3).unwrap();
    for (ts, uuid, step) in [(1.0_f64, uuid0, 1_i8), (2.0, uuid1, 2), (3.0, uuid2, 3)] {
        input_buf.write_u8(0).unwrap(); // timestamp not-null marker
        input_buf.write_f64_le(ts).unwrap();
        input_buf.write_uuid(uuid).unwrap();
        input_buf.write_u8(0).unwrap(); // breakdown not-null marker
        input_buf.write_bytes(b"en").unwrap();
        input_buf.write_varint(1).unwrap();
        input_buf.write_i8(step).unwrap();
    }

    let mut reader = Cursor::new(input_buf);
    let mut writer = Cursor::new(Vec::new());
    run_rowbinary(
        &mut reader,
        &mut writer,
        Mode::Steps,
        BreakdownShape::NullableString,
    )
    .unwrap();

    let out_bytes = writer.into_inner();
    let mut out = out_bytes.as_slice();

    // send_chunk_header is input-only; output is plain RBWNAT.
    let out_cols = crate::codec::header::read_block_header(&mut out).unwrap();
    assert_eq!(out_cols.len(), 1);
    assert_eq!(out_cols[0].name, "result");

    let outer_len = out.read_varint().unwrap();
    assert_eq!(outer_len, 1);

    let step = out.read_u8().unwrap() as i8;
    assert_eq!(step, 2);

    let nullable_string = DataTypeNode::Nullable(Box::new(DataTypeNode::String));
    let breakdown =
        read_propval(&mut out, BreakdownShape::NullableString, &nullable_string).unwrap();
    assert_eq!(breakdown, PropVal::String(Bytes(b"en".to_vec())));

    let timings: Vec<f64> = RowBinaryRead::read_array(&mut out, |r| r.read_f64_le()).unwrap();
    assert_eq!(timings.len(), 2);

    let uuids_per_step: Vec<Vec<Uuid>> = RowBinaryRead::read_array(&mut out, |r| {
        RowBinaryRead::read_array(r, |r| r.read_uuid())
    })
    .unwrap();
    assert_eq!(uuids_per_step.len(), 3);

    let mut bitfield_buf = [0u8; 4];
    std::io::Read::read_exact(&mut out, &mut bitfield_buf).unwrap();
    assert_eq!(u32::from_le_bytes(bitfield_buf), 0b111);
}

#[test]
fn rowbinary_empty_input_chunk_emits_header_only() {
    // n=0 still carries a block header (schema) we must consume, and we
    // must emit an output header so CH gets schema for the empty result.
    let mut input_buf = Vec::new();
    write_chunk_header(&mut input_buf, 0).unwrap();
    write_steps_header(&mut input_buf);
    let mut reader = Cursor::new(input_buf);
    let mut writer = Cursor::new(Vec::new());
    run_rowbinary(
        &mut reader,
        &mut writer,
        Mode::Steps,
        BreakdownShape::NullableString,
    )
    .unwrap();
    let out = writer.into_inner();
    assert!(!out.is_empty());
}

#[test]
fn rowbinary_returns_ok_on_clean_eof() {
    let mut reader = Cursor::new(Vec::<u8>::new());
    let mut writer = Cursor::new(Vec::new());
    run_rowbinary(
        &mut reader,
        &mut writer,
        Mode::Steps,
        BreakdownShape::NullableString,
    )
    .unwrap();
    assert!(writer.into_inner().is_empty());
}

// Same logical fixture as the rowbinary test, but as JSONEachRow input.
#[test]
fn json_path_still_works_for_same_fixture() {
    let input = r#"{"num_steps":3,"conversion_window_limit":3600,"breakdown_attribution_type":"first_touch","funnel_order_type":"ordered","prop_vals":["en"],"optional_steps":[],"value":[{"timestamp":1.0,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]},{"timestamp":2.0,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]},{"timestamp":3.0,"uuid":"00000000-0000-0000-0000-000000000003","breakdown":"en","steps":[3]}]}
"#;
    let mut reader = std::io::BufReader::new(input.as_bytes());
    let mut writer = Cursor::new(Vec::new());
    run_json(&mut reader, &mut writer, Mode::Steps).unwrap();
    let s = String::from_utf8(writer.into_inner()).unwrap();
    assert!(s.contains("\"result\""), "json output: {s}");
    assert!(
        s.starts_with(r#"{"result":[[2,"#),
        "expected step 2 as first tuple element: {s}"
    );
}
