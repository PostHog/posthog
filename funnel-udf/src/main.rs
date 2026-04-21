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

use crate::codec::chunk::read_chunk_header;
use crate::codec::CodecResult;

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
    use std::io::Cursor;
    use uuid::Uuid;

    use crate::codec::msgpack::{
        write_array_len, write_bin, write_f64, write_sint, write_uint, write_uuid,
    };

    fn steps_single_row(buf: &mut Vec<u8>, uuid: Uuid, ts: f64, step: i8) {
        write_uint(buf, 3).unwrap(); // num_steps
        write_uint(buf, 3600).unwrap(); // conversion_window_limit
        write_bin(buf, b"first_touch").unwrap();
        write_bin(buf, b"ordered").unwrap();
        // prop_vals
        write_array_len(buf, 1).unwrap();
        write_bin(buf, b"en").unwrap();
        // optional_steps
        write_array_len(buf, 0).unwrap();
        // value: one event
        write_array_len(buf, 1).unwrap();
        write_array_len(buf, 4).unwrap(); // tuple arity
        write_f64(buf, ts).unwrap();
        write_uuid(buf, uuid).unwrap();
        write_bin(buf, b"en").unwrap();
        write_array_len(buf, 1).unwrap(); // steps
        write_sint(buf, step as i64).unwrap();
    }

    #[test]
    fn msgpack_round_trip_steps() {
        use crate::codec::chunk::write_chunk_header;
        let uuid = Uuid::parse_str("00000000-0000-0000-0000-000000000001").unwrap();
        let mut input = Vec::new();
        write_chunk_header(&mut input, 1).unwrap();
        steps_single_row(&mut input, uuid, 1.5, 1);

        let mut reader = Cursor::new(input);
        let mut writer = Cursor::new(Vec::new());
        run_msgpack(&mut reader, &mut writer, Mode::Steps).unwrap();
        assert!(!writer.into_inner().is_empty());
    }

    #[test]
    fn msgpack_returns_ok_on_clean_eof() {
        let mut reader = Cursor::new(Vec::<u8>::new());
        let mut writer = Cursor::new(Vec::new());
        run_msgpack(&mut reader, &mut writer, Mode::Steps).unwrap();
        assert!(writer.into_inner().is_empty());
    }

    #[test]
    fn json_path_still_works() {
        let input = r#"{"num_steps":3,"conversion_window_limit":3600,"breakdown_attribution_type":"first_touch","funnel_order_type":"ordered","prop_vals":["en"],"optional_steps":[],"value":[{"timestamp":1.0,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]}]}
"#;
        let mut reader = std::io::BufReader::new(input.as_bytes());
        let mut writer = Cursor::new(Vec::new());
        run_json(&mut reader, &mut writer, Mode::Steps).unwrap();
        let s = String::from_utf8(writer.into_inner()).unwrap();
        assert!(s.contains("\"result\""), "json output: {s}");
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
    MsgPack,
}

struct Cli {
    mode: Mode,
    format: Format,
}

// CLI contract:
//   aggregate_funnel <mode>             -> MsgPack (default, matches XML config)
//   aggregate_funnel <mode> --json      -> JSONEachRow (debug / benchmark)
// mode = "steps" | "trends"
//
// Breakdown shape is detected at runtime from the first wire marker in
// `prop_vals` (or the first event's breakdown slot if prop_vals is empty),
// so one binary serves all three variants.
fn parse_cli(argv: &[String]) -> std::result::Result<Cli, String> {
    let mut mode: Option<Mode> = None;
    let mut format = Format::MsgPack;

    for arg in &argv[1..] {
        match arg.as_str() {
            "steps" => mode = Some(Mode::Steps),
            "trends" => mode = Some(Mode::Trends),
            "--json" => format = Format::Json,
            "--msgpack" => format = Format::MsgPack,
            s => return Err(format!("unknown argument: {s:?}")),
        }
    }

    let mode = mode.ok_or_else(|| "missing mode (steps | trends)".to_string())?;
    Ok(Cli { mode, format })
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

// Given an unknown-shape prop_vals array, read one "first value" peek to
// determine shape, then re-read from the start. Since we can't seek on stdin,
// we use the BufReader's fill_buf to peek.
fn detect_shape<R: BufRead>(reader: &mut R) -> CodecResult<types::BreakdownShape> {
    use crate::codec::CodecError;
    // At this point the next bytes are: prop_vals array length marker + elements.
    // We peek past the array length marker to sniff the first element.
    // Because MsgPack array length can be 1 byte (fixarray) or 3/5 bytes
    // (array16/array32), we consume the length, then look at the next marker.
    // But we still need those bytes to be unread for the main loop — so we
    // can't use this approach with a BufReader that doesn't rewind.
    //
    // Alternative used here: peek at first byte only; if it's a fixarray with
    // len>0, we can look at the byte after the marker. If not fixarray or
    // len==0, we conservatively default to NullableString and rely on the
    // actual read to surface a mismatch error.
    let buf = reader.fill_buf().map_err(CodecError::Io)?;
    if buf.is_empty() {
        return Err(CodecError::UnexpectedEof);
    }
    let first = buf[0];
    // Fixarray 0x90..=0x9f: length in low 4 bits. Element starts at buf[1].
    if (0x90..=0x9f).contains(&first) && first != 0x90 && buf.len() >= 2 {
        if let Some(shape) = io::propval::shape_from_marker(rmp::Marker::from_u8(buf[1])) {
            return Ok(shape);
        }
    }
    // Default when ambiguous — the actual reader will error if wrong.
    Ok(types::BreakdownShape::NullableString)
}

fn run_msgpack<R: BufRead, W: Write>(
    reader: &mut R,
    writer: &mut W,
    mode: Mode,
) -> CodecResult<()> {
    loop {
        let n = match read_chunk_header(reader)? {
            Some(n) => n,
            None => return Ok(()),
        };

        match mode {
            Mode::Steps => {
                let mut results = Vec::with_capacity(n as usize);
                let mut shape = types::BreakdownShape::NullableString;
                for i in 0..n {
                    if i == 0 {
                        // Advance past the first three args (num_steps, conv_window,
                        // attribution, order_type) to get to prop_vals. Actually we
                        // can peek shape later from the first prop_vals element;
                        // simpler: call a "read_and_detect" variant.
                        //
                        // Instead of juggling, just detect shape per row on the
                        // first row by reading args with shape=NullableString and
                        // if it fails, retry. That's more complexity than value.
                        //
                        // Practical choice: detect shape via a scan of the first
                        // row's prop_vals marker using BufReader peek. We know the
                        // first 4 args have fixed sizes-ish, but prop_vals length
                        // is variable. Easier: peek the first row entirely into
                        // a Vec, decode shape from it, then decode args from buf.
                        // But BufReader buffer may not hold a whole row.
                        //
                        // Cleanest: add a mode where read_args takes an "auto-detect"
                        // option and the first prop_val read picks shape. Done below.
                        let (args, detected) = io::steps_io::read_args_auto(reader)?;
                        shape = detected;
                        results.push(steps::run(&args));
                    } else {
                        let args = io::steps_io::read_args(reader, shape)?;
                        results.push(steps::run(&args));
                    }
                }
                // Output: for each row we emit one outer Array of result tuples.
                for r in &results {
                    io::steps_io::write_results(writer, r, shape)?;
                }
            }
            Mode::Trends => {
                let mut results = Vec::with_capacity(n as usize);
                let mut shape = types::BreakdownShape::NullableString;
                for i in 0..n {
                    if i == 0 {
                        let (args, detected) = io::trends_io::read_args_auto(reader)?;
                        shape = detected;
                        results.push(trends::run(&args));
                    } else {
                        let args = io::trends_io::read_args(reader, shape)?;
                        results.push(trends::run(&args));
                    }
                }
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
                "funnels: {e}\n\nusage: {} <steps|trends> [--json]\n  default format is MsgPack; breakdown shape is detected from the first prop_vals element",
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
        Format::MsgPack => run_msgpack(&mut reader, &mut writer, cli.mode).map_err(Into::into),
    };

    // Silence dead-code warning for the test-only helper
    let _ = detect_shape::<std::io::Cursor<&[u8]>>;

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            let _ = writeln!(std::io::stderr(), "funnels error: {e}");
            ExitCode::FAILURE
        }
    }
}
