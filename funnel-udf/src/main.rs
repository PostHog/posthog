#![allow(unstable_name_collisions)]

mod codec;
mod io;
mod parsing;
mod steps;
mod trends;
mod types;
mod unordered_steps;
mod unordered_trends;

use std::env;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::process::ExitCode;

pub use types::{Bytes, PropVal};

use crate::codec::chunk::{read_chunk_header, write_chunk_header};
use crate::codec::CodecResult;
use crate::types::BreakdownShape;

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(r#""hello""#, PropVal::String(Bytes(b"hello".to_vec())))]
    #[case(r#"42"#, PropVal::Int(42))]
    #[case(r#"4503599627370496"#, PropVal::Int(4503599627370496))] // 2^52 (NOT_IN_COHORT_ID)
    #[case(r#"["a","b"]"#, PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())]))]
    #[case(r#"[1, 2, 3]"#, PropVal::VecInt(vec![1, 2, 3]))]
    #[case(r#"[4503599627370496]"#, PropVal::VecInt(vec![4503599627370496]))]
    fn test_propval_deserialization(#[case] json: &str, #[case] expected: PropVal) {
        let result: PropVal = serde_json::from_str(json).unwrap();
        assert_eq!(result, expected);
    }
}

#[cfg(test)]
mod e2e {
    use super::*;
    use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
    use crate::io::propval::{read_propval, write_propval};
    use std::io::Cursor;
    use uuid::Uuid;

    // A single-row, minimal-shape fixture that exercises the full rowbinary pipeline:
    // chunk header -> read_args -> steps::run -> write_results -> chunk header, all
    // through the same run_rowbinary entry main.rs uses.
    //
    // The fixture: 3-step ordered funnel, one breakdown "en", one user with three
    // events hitting steps 1/2/3 in order. Expected final step = 2 (0-indexed).
    #[test]
    fn rowbinary_steps_round_trip_matches_json_semantics() {
        let shape = BreakdownShape::NullableString;
        let uuid0 = Uuid::parse_str("00000000-0000-0000-0000-000000000001").unwrap();
        let uuid1 = Uuid::parse_str("00000000-0000-0000-0000-000000000002").unwrap();
        let uuid2 = Uuid::parse_str("00000000-0000-0000-0000-000000000003").unwrap();

        // Build chunk on wire: "1\n" + one row of rowbinary.
        let mut input_buf = Vec::new();
        write_chunk_header(&mut input_buf, 1).unwrap();

        // num_steps, conversion_window_limit, breakdown_attribution_type, funnel_order_type, prop_vals, optional_steps, value
        input_buf.write_u8(3).unwrap();
        input_buf.write_u64_le(3600).unwrap();
        input_buf.write_string("first_touch").unwrap();
        input_buf.write_string("ordered").unwrap();
        // prop_vals: [en]
        input_buf.write_varint(1).unwrap();
        write_propval(
            &mut input_buf,
            &PropVal::String(Bytes(b"en".to_vec())),
            shape,
        )
        .unwrap();
        // optional_steps: []
        input_buf.write_varint(0).unwrap();
        // value: 3 events
        input_buf.write_varint(3).unwrap();
        for (ts, uuid, step) in [(1.0_f64, uuid0, 1_i8), (2.0, uuid1, 2), (3.0, uuid2, 3)] {
            input_buf.write_u8(0).unwrap(); // Nullable(Float64) non-null marker
            input_buf.write_f64_le(ts).unwrap();
            input_buf.write_uuid(uuid).unwrap();
            write_propval(
                &mut input_buf,
                &PropVal::String(Bytes(b"en".to_vec())),
                shape,
            )
            .unwrap();
            input_buf.write_varint(1).unwrap();
            input_buf.write_i8(step).unwrap();
        }

        let mut reader = Cursor::new(input_buf);
        let mut writer = Cursor::new(Vec::new());
        run_rowbinary(&mut reader, &mut writer, Mode::Steps, shape).unwrap();

        // Decode the output.
        let out_bytes = writer.into_inner();
        let mut out = out_bytes.as_slice();
        // chunk header "1\n"
        let header_end = out.iter().position(|&b| b == b'\n').unwrap();
        let header_n: u64 = std::str::from_utf8(&out[..header_end])
            .unwrap()
            .parse()
            .unwrap();
        assert_eq!(header_n, 1);
        out = &out[header_end + 1..];

        // One output row: Array(Tuple(Int8, Nullable(String), Array(Float64), Array(Array(UUID)), UInt32))
        let outer_len = out.read_varint().unwrap();
        assert_eq!(outer_len, 1, "one prop_val in -> one result row out");

        let step = out.read_i8().unwrap();
        assert_eq!(step, 2, "reached step index 2 (0-indexed third step)");

        let breakdown = read_propval(&mut out, shape).unwrap();
        assert_eq!(breakdown, PropVal::String(Bytes(b"en".to_vec())));

        let timings: Vec<f64> = RowBinaryRead::read_array(&mut out, |r| r.read_f64_le()).unwrap();
        assert_eq!(
            timings.len(),
            2,
            "two inter-step conversion deltas for a 3-step completion"
        );

        let uuids_per_step: Vec<Vec<Uuid>> = RowBinaryRead::read_array(&mut out, |r| {
            RowBinaryRead::read_array(r, |r| r.read_uuid())
        })
        .unwrap();
        assert_eq!(uuids_per_step.len(), 3);

        let bitfield = out.read_u32_le().unwrap();
        assert_eq!(bitfield, 0b111, "steps 1/2/3 all set");
    }

    #[test]
    fn rowbinary_emits_empty_chunk_header_on_empty_input_chunk() {
        let shape = BreakdownShape::NullableString;
        let mut input_buf = Vec::new();
        write_chunk_header(&mut input_buf, 0).unwrap();
        let mut reader = Cursor::new(input_buf);
        let mut writer = Cursor::new(Vec::new());
        run_rowbinary(&mut reader, &mut writer, Mode::Steps, shape).unwrap();
        let out = writer.into_inner();
        assert_eq!(out, b"0\n");
    }

    #[test]
    fn rowbinary_returns_ok_on_clean_eof() {
        // No chunk header at all -> eof -> clean exit
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

    #[test]
    fn json_path_still_works_for_same_fixture() {
        // Same logical fixture as the rowbinary test, but as JSONEachRow input.
        let input = r#"{"num_steps":3,"conversion_window_limit":3600,"breakdown_attribution_type":"first_touch","funnel_order_type":"ordered","prop_vals":["en"],"optional_steps":[],"value":[{"timestamp":1.0,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]},{"timestamp":2.0,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]},{"timestamp":3.0,"uuid":"00000000-0000-0000-0000-000000000003","breakdown":"en","steps":[3]}]}
"#;
        let mut reader = std::io::BufReader::new(input.as_bytes());
        let mut writer = Cursor::new(Vec::new());
        run_json(&mut reader, &mut writer, Mode::Steps).unwrap();
        let s = String::from_utf8(writer.into_inner()).unwrap();
        // Light shape check: output is JSON wrapping a single result tuple whose first
        // element (step reached, 0-indexed) is 2.
        assert!(s.contains("\"result\""), "json output: {s}");
        assert!(
            s.starts_with(r#"{"result":[[2,"#),
            "expected step 2 as first tuple element: {s}"
        );
    }
}

#[derive(Clone, Copy, Debug)]
enum Mode {
    Steps,
    Trends,
}

#[derive(Clone, Copy, Debug)]
enum Format {
    Json,
    RowBinary,
}

struct Cli {
    mode: Mode,
    format: Format,
    shape: Option<BreakdownShape>,
}

// CLI contract:
//   aggregate_funnel <mode> <shape>           -> RowBinary (default)
//   aggregate_funnel <mode> --json            -> JSON (opt-in for debugging / benchmark)
//   aggregate_funnel <mode>                   -> error (must pick a format)
// mode  = "steps" | "trends"
// shape = "nullable_string" | "array_string" | "u64"
//
// --rowbinary is also accepted as an explicit flag for symmetry with --json; it
// requires a shape.
fn parse_cli(argv: &[String]) -> std::result::Result<Cli, String> {
    let mut mode: Option<Mode> = None;
    let mut explicit_format: Option<Format> = None;
    let mut shape: Option<BreakdownShape> = None;

    for arg in &argv[1..] {
        match arg.as_str() {
            "steps" => mode = Some(Mode::Steps),
            "trends" => mode = Some(Mode::Trends),
            "--json" => explicit_format = Some(Format::Json),
            "--rowbinary" => explicit_format = Some(Format::RowBinary),
            s => match BreakdownShape::parse(s) {
                Some(sh) => shape = Some(sh),
                None => return Err(format!("unknown argument: {s:?}")),
            },
        }
    }

    let mode = mode.ok_or_else(|| "missing mode (steps | trends)".to_string())?;

    let format = match (explicit_format, shape) {
        (Some(f), _) => f,
        (None, Some(_)) => Format::RowBinary,
        (None, None) => {
            return Err(
                "must specify a shape (nullable_string | array_string | u64) for RowBinary, or --json"
                    .into(),
            );
        }
    };

    if matches!(format, Format::RowBinary) && shape.is_none() {
        return Err(
            "--rowbinary requires a shape argument (nullable_string | array_string | u64)".into(),
        );
    }

    Ok(Cli {
        mode,
        format,
        shape,
    })
}

fn run_json<R: BufRead, W: Write>(reader: R, writer: &mut W, mode: Mode) -> std::io::Result<()> {
    for line in reader.lines() {
        let line = line?;
        let output = match mode {
            Mode::Steps => steps::process_line(&line),
            Mode::Trends => trends::process_line(&line),
        };
        writeln!(writer, "{}", output)?;
        writer.flush()?;
    }
    Ok(())
}

fn run_rowbinary<R: BufRead, W: Write>(
    reader: &mut R,
    writer: &mut W,
    mode: Mode,
    shape: BreakdownShape,
) -> CodecResult<()> {
    loop {
        let n = match read_chunk_header(reader)? {
            Some(n) => n,
            None => return Ok(()),
        };
        match mode {
            Mode::Steps => {
                let mut results = Vec::with_capacity(n as usize);
                for _ in 0..n {
                    let args = io::steps_io::read_args(reader, shape)?;
                    results.push(steps::run(&args));
                }
                write_chunk_header(writer, n)?;
                for r in &results {
                    io::steps_io::write_results(writer, r, shape)?;
                }
            }
            Mode::Trends => {
                let mut results = Vec::with_capacity(n as usize);
                for _ in 0..n {
                    let args = io::trends_io::read_args(reader, shape)?;
                    results.push(trends::run(&args));
                }
                write_chunk_header(writer, n)?;
                for r in &results {
                    io::trends_io::write_results(writer, r, shape)?;
                }
            }
        }
        writer.flush()?;
    }
}

fn main() -> ExitCode {
    let argv: Vec<String> = env::args().collect();
    let cli = match parse_cli(&argv) {
        Ok(c) => c,
        Err(e) => {
            let _ = writeln!(
                std::io::stderr(),
                "funnels: {e}\n\nusage: {} <steps|trends> (<shape> | --json)\n  shape = nullable_string | array_string | u64 (implies RowBinary)\n  --json for JSONEachRow mode",
                argv.first().map(String::as_str).unwrap_or("aggregate_funnel")
            );
            return ExitCode::FAILURE;
        }
    };

    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::with_capacity(64 * 1024, stdin.lock());
    let mut writer = BufWriter::with_capacity(64 * 1024, stdout.lock());

    let result: std::result::Result<(), Box<dyn std::error::Error>> = match cli.format {
        Format::Json => run_json(&mut reader, &mut writer, cli.mode).map_err(Into::into),
        Format::RowBinary => run_rowbinary(&mut reader, &mut writer, cli.mode, cli.shape.unwrap())
            .map_err(Into::into),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            let _ = writeln!(std::io::stderr(), "funnels error: {e}");
            ExitCode::FAILURE
        }
    }
}
