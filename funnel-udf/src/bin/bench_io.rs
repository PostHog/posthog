// Benchmark harness for funnel UDF IO performance. Designed to hit the v12
// trends-output failure mode (many skinny rows per UDF call). Spawns a target
// funnel binary, drives it with a synthetic RBWNAT input, and times round-
// trips. Use to compare the deployed v12 binary against the v13 fix on the
// same machine with the same toolchain.
//
// usage:
//   bench_io [--json|--raw] <path_to_funnel_binary> [iterations] [buckets_per_user] [users_per_chunk]
//
// defaults: iterations=200, buckets_per_user=5000, users_per_chunk=1.
//
// modes:
//   (default) RowBinaryWithNamesAndTypes: per-chunk block header on the wire.
//   --json    JSONEachRow: one JSON line per call, no chunk/block headers.
//   --raw     RowBinary: chunk header only, no per-chunk block header on
//             either side (experimental; uses `--raw-rowbinary` mode in
//             funnels). Lets you measure how much per-call cost remains in
//             the (already-cached) header read+write vs everything else.
//
// In --json mode, `users_per_chunk` is ignored and each iteration sends one
// JSON line (one Args). The funnels binary is invoked with --json. This lets
// you A/B the v12 RowBinary path against the v11 JSON path for the SAME
// workload, isolating the IO/codec overhead from the funnel algorithm.
//
// users_per_chunk > 1 mirrors the production pattern. Production trends
// queries observed on us.posthog.com (top-5 slow queries pre-fix) had a
// fixed shape:
//   - 2-step funnel, ordered, first_touch attribution
//   - ~53-91 daily buckets per person
//   - no real breakdown (single empty NullableString prop_val)
//   - CPU 7.4s of 322s wall (~2.3% utilization) — process is wall-clock
//     bound, not compute bound, so the per-call IO/pipe overhead matters
//   - Many tiny calls (millions per query, ~3 events each) is the worst case

use std::env;
use std::fmt::Write as _;
use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use clickhouse_types::{Column, DataTypeNode};
use funnels::codec::chunk::write_chunk_header;
use funnels::codec::header::{read_block_header, write_block_header};
use funnels::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use uuid::Uuid;

// One UDF invocation = one chunk-header line + RBWNAT block-header + N Args
// rows (one per user). Each Args row carries that user's events. The trends
// algorithm groups each user's events by `interval_start` and emits one
// ResultStruct per (interval_start, prop_val) where the funnel completes,
// so output cardinality = users * buckets_per_user (since every bucket
// completes here).
fn build_trends_input(
    users_per_chunk: u64,
    buckets_per_user: u64,
    conversion_window: u64,
    include_block_header: bool,
) -> Vec<u8> {
    let mut buf: Vec<u8> = Vec::new();

    write_chunk_header(&mut buf, users_per_chunk).expect("chunk header");

    if include_block_header {
        let nullable_string = DataTypeNode::Nullable(Box::new(DataTypeNode::String));
        let cols = vec![
            Column::new("from_step".into(), DataTypeNode::UInt8),
            Column::new("to_step".into(), DataTypeNode::UInt8),
            Column::new("num_steps".into(), DataTypeNode::UInt8),
            Column::new("conversion_window_limit".into(), DataTypeNode::UInt64),
            Column::new("breakdown_attribution_type".into(), DataTypeNode::String),
            Column::new("funnel_order_type".into(), DataTypeNode::String),
            Column::new(
                "prop_vals".into(),
                DataTypeNode::Array(Box::new(nullable_string.clone())),
            ),
            Column::new(
                "value".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                    DataTypeNode::Nullable(Box::new(DataTypeNode::Float64)),
                    DataTypeNode::UInt64,
                    DataTypeNode::UUID,
                    nullable_string,
                    DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
                ]))),
            ),
        ];
        write_block_header(&mut buf, &cols).expect("block header");
    }

    let base_ts = 1_700_000_000u64;
    for user in 0..users_per_chunk {
        // Args row scalars — same shape for every user, mirrors how
        // ClickHouse passes per-row args even when most are constant.
        // from_step=0, to_step=1, num_steps=2 — minimal 2-step funnel.
        buf.write_u8(0).unwrap();
        buf.write_u8(1).unwrap();
        buf.write_u8(2).unwrap();
        buf.write_u64_le(conversion_window).unwrap();
        buf.write_bytes(b"first_touch").unwrap();
        buf.write_bytes(b"ordered").unwrap();

        // prop_vals = [""]
        buf.write_varint(1).unwrap();
        buf.write_u8(0).unwrap(); // not-null
        buf.write_bytes(b"").unwrap();

        // value: 2 events per bucket, each bucket completes the funnel.
        buf.write_varint(buckets_per_user * 2).unwrap();
        for b in 0..buckets_per_user {
            let interval_start = base_ts + b * 86_400;
            for (step, off, uuid_lo) in [(1i8, 10.0, 1u64), (2i8, 20.0, 2u64)] {
                buf.write_u8(0).unwrap(); // timestamp not-null
                buf.write_f64_le(interval_start as f64 + off).unwrap();
                buf.write_u64_le(interval_start).unwrap();
                buf.write_uuid(Uuid::from_u64_pair(user, b * 2 + uuid_lo))
                    .unwrap();
                buf.write_u8(0).unwrap(); // breakdown not-null
                buf.write_bytes(b"").unwrap();
                buf.write_varint(1).unwrap();
                buf.write_i8(step).unwrap();
            }
        }
    }

    buf
}

// Parses one chunk's RowBinary[WithNamesAndTypes] response. In RBWNAT mode
// the block header comes first; in raw mode it's omitted. Each of the
// `n_rows` rows emits one Array(Tuple(...)) value (varint outer_len + N
// ResultStructs of shape (UInt64, Int8, Nullable(String), UUID)). Returns
// the total ResultStruct count summed across all rows.
fn drain_one_response<R: Read>(
    reader: &mut R,
    n_rows: usize,
    expect_block_header: bool,
) -> std::io::Result<usize> {
    if expect_block_header {
        let cols = read_block_header(reader).map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::InvalidData, format!("header: {e}"))
        })?;
        if cols.len() != 1 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("expected 1 output column, got {}", cols.len()),
            ));
        }
    }
    let mut total = 0usize;
    for _row in 0..n_rows {
        let outer_len = reader.read_varint().map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::InvalidData, format!("outer: {e}"))
        })? as usize;
        for _ in 0..outer_len {
            let _interval = reader.read_u64_le().map_err(io_err("interval"))?;
            let _sign = reader.read_u8().map_err(io_err("sign"))?;
            let nm = reader.read_u8().map_err(io_err("null marker"))?;
            if nm == 0 {
                let _bytes = reader.read_bytes().map_err(io_err("breakdown"))?;
            }
            let _uuid = reader.read_uuid().map_err(io_err("uuid"))?;
        }
        total += outer_len;
    }
    Ok(total)
}

fn io_err<E: std::fmt::Display>(ctx: &'static str) -> impl Fn(E) -> std::io::Error {
    move |e| std::io::Error::new(std::io::ErrorKind::InvalidData, format!("{ctx}: {e}"))
}

// JSONEachRow input: one line per UDF call. Mirror of build_trends_input
// but for the v11 JSON path; the funnels binary still uses the same
// process_line code on this branch (unchanged in v12, retained as a
// benchmark reference).
fn build_trends_json_line(buckets_per_user: u64, conversion_window: u64) -> String {
    let mut s = String::with_capacity(256 + (buckets_per_user as usize) * 100);
    write!(
        &mut s,
        "{{\"from_step\":0,\"to_step\":1,\"num_steps\":2,\"conversion_window_limit\":{},\
         \"breakdown_attribution_type\":\"first_touch\",\"funnel_order_type\":\"ordered\",\
         \"prop_vals\":[\"\"],\"value\":[",
        conversion_window
    )
    .unwrap();
    let base_ts = 1_700_000_000u64;
    let mut first = true;
    for b in 0..buckets_per_user {
        let interval_start = base_ts + b * 86_400;
        for (step, off, uuid_lo) in [(1i8, 10.0, 1u64), (2i8, 20.0, 2u64)] {
            if !first {
                s.push(',');
            }
            first = false;
            let uuid = Uuid::from_u64_pair(0, b * 2 + uuid_lo);
            write!(
                &mut s,
                "{{\"timestamp\":{},\"interval_start\":{},\"uuid\":\"{}\",\
                 \"breakdown\":\"\",\"steps\":[{}]}}",
                interval_start as f64 + off,
                interval_start,
                uuid,
                step,
            )
            .unwrap();
        }
    }
    s.push_str("]}\n");
    s
}

fn percentile(sorted: &[Duration], p: f64) -> Duration {
    if sorted.is_empty() {
        return Duration::ZERO;
    }
    let idx = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[idx]
}

fn fmt_dur(d: Duration) -> String {
    let us = d.as_secs_f64() * 1_000_000.0;
    if us >= 1000.0 {
        format!("{:.2} ms", us / 1000.0)
    } else {
        format!("{:.1} us", us)
    }
}

fn run_rowbinary_bench(
    binary: &str,
    iterations: usize,
    buckets: u64,
    users: u64,
    raw: bool,
) -> Vec<Duration> {
    let input = build_trends_input(users, buckets, 86_400, !raw);
    let expected_results = (users * buckets) as usize;
    let label = if raw { "raw-rowbinary" } else { "rowbinary" };

    println!(
        "[{}] users={} buckets/user={} => {} ResultStructs per call, input {} bytes",
        label,
        users,
        buckets,
        expected_results,
        input.len()
    );

    let funnels_format = if raw { "--raw-rowbinary" } else { "--rowbinary" };
    let mut child = Command::new(binary)
        .args(["trends", "--variant=plain", funnels_format])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("failed to spawn target binary");

    let mut stdin = child.stdin.take().expect("stdin");
    let stdout = child.stdout.take().expect("stdout");
    let mut stdout = BufReader::with_capacity(256 * 1024, stdout);

    stdin.write_all(&input).expect("warmup write");
    stdin.flush().expect("warmup flush");
    let warmup_n =
        drain_one_response(&mut stdout, users as usize, !raw).expect("warmup drain");
    assert_eq!(
        warmup_n, expected_results,
        "[{}] warmup output cardinality mismatch: got {} want {}",
        label, warmup_n, expected_results
    );

    let mut timings: Vec<Duration> = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let t0 = Instant::now();
        stdin.write_all(&input).expect("write");
        stdin.flush().expect("flush");
        let n = drain_one_response(&mut stdout, users as usize, !raw).expect("drain");
        let dt = t0.elapsed();
        debug_assert_eq!(n, expected_results);
        timings.push(dt);
    }

    drop(stdin);
    let _ = child.wait();
    timings
}

fn run_json_bench(binary: &str, iterations: usize, buckets: u64) -> Vec<Duration> {
    let line = build_trends_json_line(buckets, 86_400);
    println!(
        "[json] buckets/call={} => {} ResultStructs per call, input {} bytes/line",
        buckets,
        buckets,
        line.len()
    );

    let mut child = Command::new(binary)
        .args(["trends", "--json", "--variant=plain"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("failed to spawn target binary");

    let mut stdin = child.stdin.take().expect("stdin");
    let stdout = child.stdout.take().expect("stdout");
    let mut stdout = BufReader::with_capacity(256 * 1024, stdout);

    // Warmup: send one line, read one line.
    stdin.write_all(line.as_bytes()).expect("warmup write");
    stdin.flush().expect("warmup flush");
    let mut scratch = String::new();
    stdout.read_line(&mut scratch).expect("warmup read");
    assert!(
        scratch.contains("\"result\""),
        "[json] expected \"result\" in output, got: {}",
        scratch
    );

    let mut timings: Vec<Duration> = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        scratch.clear();
        let t0 = Instant::now();
        stdin.write_all(line.as_bytes()).expect("write");
        stdin.flush().expect("flush");
        stdout.read_line(&mut scratch).expect("read line");
        let dt = t0.elapsed();
        timings.push(dt);
    }

    drop(stdin);
    let _ = child.wait();
    timings
}

fn report(label: &str, mut timings: Vec<Duration>) {
    timings.sort();
    let sum: Duration = timings.iter().copied().sum();
    let mean = sum / timings.len() as u32;
    let p50 = percentile(&timings, 0.50);
    let p90 = percentile(&timings, 0.90);
    let p99 = percentile(&timings, 0.99);
    let min = *timings.first().unwrap();
    let max = *timings.last().unwrap();
    println!(
        "{label:<14} mean={:>9} min={:>9} p50={:>9} p90={:>9} p99={:>9} max={:>9}",
        fmt_dur(mean),
        fmt_dur(min),
        fmt_dur(p50),
        fmt_dur(p90),
        fmt_dur(p99),
        fmt_dur(max),
    );
}

#[derive(Clone, Copy)]
enum BenchMode {
    Rowbinary,
    Json,
    Raw,
}

fn main() {
    let mut argv: Vec<String> = env::args().collect();
    let mut mode = BenchMode::Rowbinary;
    if argv.len() > 1 {
        match argv[1].as_str() {
            "--json" => {
                mode = BenchMode::Json;
                argv.remove(1);
            }
            "--raw" => {
                mode = BenchMode::Raw;
                argv.remove(1);
            }
            _ => {}
        }
    }

    if argv.len() < 2 {
        eprintln!(
            "usage: {} [--json|--raw] <path_to_funnel_binary> [iterations=200] [buckets_per_user=5000] [users_per_chunk=1]",
            argv.first().map(String::as_str).unwrap_or("bench_io")
        );
        std::process::exit(2);
    }
    let binary = &argv[1];
    let iterations: usize = argv.get(2).and_then(|s| s.parse().ok()).unwrap_or(200);
    let buckets: u64 = argv.get(3).and_then(|s| s.parse().ok()).unwrap_or(5_000);
    let users: u64 = argv.get(4).and_then(|s| s.parse().ok()).unwrap_or(1);

    let mode_label = match mode {
        BenchMode::Rowbinary => "rowbinary",
        BenchMode::Json => "json",
        BenchMode::Raw => "raw-rowbinary",
    };

    println!("target:     {}", binary);
    println!("iterations: {}", iterations);
    println!("mode:       {}", mode_label);
    println!();

    let timings = match mode {
        BenchMode::Json => run_json_bench(binary, iterations, buckets),
        BenchMode::Rowbinary => run_rowbinary_bench(binary, iterations, buckets, users, false),
        BenchMode::Raw => run_rowbinary_bench(binary, iterations, buckets, users, true),
    };

    println!();
    report(mode_label, timings);
}
