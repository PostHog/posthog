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
use crate::codec::header::{read_block_header, write_block_header};
use crate::codec::CodecResult;
use crate::types::BreakdownShape;

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
    shape: BreakdownShape,
}

// CLI:
//   aggregate_funnel <steps|trends> --variant=<plain|cohort|array>
//     RowBinaryWithNamesAndTypes (default)
//   aggregate_funnel <steps|trends> --variant=<...> --json
//     JSONEachRow (debug / benchmark)
//
// `--variant` fixes the breakdown wire shape for this process's lifetime.
// Each XML <function> block (aggregate_funnel, aggregate_funnel_cohort,
// aggregate_funnel_array) gets its own executable_pool, so the variant is
// known at startup and never changes per call.
fn parse_cli(argv: &[String]) -> std::result::Result<Cli, String> {
    let mut mode: Option<Mode> = None;
    let mut format = Format::RowBinary;
    let mut shape: Option<BreakdownShape> = None;

    for arg in &argv[1..] {
        let s = arg.as_str();
        match s {
            "steps" => mode = Some(Mode::Steps),
            "trends" => mode = Some(Mode::Trends),
            "--json" => format = Format::Json,
            "--rowbinary" => format = Format::RowBinary,
            _ if s.starts_with("--variant=") => {
                shape = Some(match &s["--variant=".len()..] {
                    "plain" => BreakdownShape::NullableString,
                    "cohort" => BreakdownShape::U64,
                    "array" => BreakdownShape::ArrayString,
                    v => return Err(format!("unknown --variant value: {v:?}")),
                });
            }
            _ => return Err(format!("unknown argument: {s:?}")),
        }
    }

    let mode = mode.ok_or_else(|| "missing mode (steps | trends)".to_string())?;
    let shape = shape.ok_or_else(|| "missing --variant=<plain|cohort|array>".to_string())?;
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
    // One loop iteration per UDF invocation. executable_pool keeps us alive
    // across invocations to skip fork/exec; each invocation's input/output is
    // self-contained (own `N\n` chunk header, own RBWNAT block header + rows).
    loop {
        let n = match read_chunk_header(reader)? {
            Some(n) => n,
            None => return Ok(()),
        };
        let columns = read_block_header(reader)?;

        match mode {
            Mode::Steps => {
                let mut results = Vec::with_capacity(n as usize);
                for _ in 0..n {
                    let args = io::steps_io::read_args(reader, shape, &columns)?;
                    results.push(steps::run(&args));
                }
                let out_cols = io::steps_io::output_columns(shape);
                write_block_header(writer, &out_cols)?;
                for r in &results {
                    io::steps_io::write_results(writer, r, shape)?;
                }
            }
            Mode::Trends => {
                let mut results = Vec::with_capacity(n as usize);
                for _ in 0..n {
                    let args = io::trends_io::read_args(reader, shape, &columns)?;
                    results.push(trends::run(&args));
                }
                let out_cols = io::trends_io::output_columns(shape);
                write_block_header(writer, &out_cols)?;
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
                "funnels: {e}\n\nusage: {} <steps|trends> --variant=<plain|cohort|array> [--json]\n  default format is RowBinaryWithNamesAndTypes; --variant pins the breakdown wire shape",
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
        Format::RowBinary => {
            run_rowbinary(&mut reader, &mut writer, cli.mode, cli.shape).map_err(Into::into)
        }
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            let _ = writeln!(std::io::stderr(), "funnels error: {e}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod e2e_tests;
