// Direct microbenchmark of `trends_io::write_results` against two sink types:
//   1. BufWriter<Vec<u8>> with 64 KiB capacity — matches the v12 production
//      writer shape (BufWriter<StdoutLock> in main.rs).
//   2. Bare Vec<u8> — the v13 fix's per-chunk accumulator shape.
//
// This isolates the per-output-row writer overhead from process IPC, the
// funnel algorithm, and pipe roundtrips. If the brief's diagnosis is correct,
// (1) should be materially slower than (2) for trends-shaped output.
//
// usage:
//   bench_write [num_results=50000] [iterations=200]

use std::io::BufWriter;
use std::time::{Duration, Instant};

use funnels::codec::header::write_block_header;
use funnels::io::trends_io::{output_columns, write_results};
use funnels::trends::ResultStruct;
use funnels::types::{BreakdownShape, Bytes, PropVal};
use uuid::Uuid;

fn build_results(n: usize) -> Vec<ResultStruct> {
    (0..n as u64)
        .map(|i| {
            ResultStruct(
                1_700_000_000 + i * 86_400,
                if i % 2 == 0 { 1 } else { -1 },
                PropVal::String(Bytes(b"".to_vec())),
                Uuid::from_u64_pair(i, i),
            )
        })
        .collect()
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

fn report(label: &str, timings: &mut Vec<Duration>) {
    timings.sort();
    let sum: Duration = timings.iter().copied().sum();
    let mean = sum / timings.len() as u32;
    let min = *timings.first().unwrap();
    let p50 = percentile(timings, 0.50);
    let p90 = percentile(timings, 0.90);
    let p99 = percentile(timings, 0.99);
    let max = *timings.last().unwrap();
    println!(
        "{label:<28} mean={:>9} min={:>9} p50={:>9} p90={:>9} p99={:>9} max={:>9}",
        fmt_dur(mean),
        fmt_dur(min),
        fmt_dur(p50),
        fmt_dur(p90),
        fmt_dur(p99),
        fmt_dur(max),
    );
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let n: usize = argv
        .get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);
    let iters: usize = argv
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(200);
    let shape = BreakdownShape::NullableString;
    let cols = output_columns(shape);
    let results = build_results(n);

    println!("microbench: trends_io::write_results");
    println!("  num_results = {n}");
    println!("  iterations  = {iters}");
    println!();

    // 1. BufWriter<Vec<u8>> with 64 KiB cap — mirrors v12's runtime sink.
    {
        let mut timings: Vec<Duration> = Vec::with_capacity(iters);
        let mut backing: Vec<u8> = Vec::with_capacity(8 * 1024 * 1024);
        for _ in 0..iters {
            backing.clear();
            let mut w = BufWriter::with_capacity(64 * 1024, &mut backing);
            let t0 = Instant::now();
            write_block_header(&mut w, &cols).unwrap();
            write_results(&mut w, &results, shape).unwrap();
            // Mirror what run_rowbinary does at end of chunk: flush.
            std::io::Write::flush(&mut w).unwrap();
            timings.push(t0.elapsed());
        }
        report("BufWriter<Vec<u8>>(64KiB)", &mut timings);
    }

    // 2. Bare Vec<u8> with 64 KiB initial cap — mirrors v13's runtime sink.
    {
        let mut timings: Vec<Duration> = Vec::with_capacity(iters);
        let mut backing: Vec<u8> = Vec::with_capacity(8 * 1024 * 1024);
        for _ in 0..iters {
            backing.clear();
            let t0 = Instant::now();
            write_block_header(&mut backing, &cols).unwrap();
            write_results(&mut backing, &results, shape).unwrap();
            timings.push(t0.elapsed());
        }
        report("Vec<u8> (preallocated)", &mut timings);
    }

    // 3. Vec<u8> starting from zero capacity, no preallocation — pessimistic.
    {
        let mut timings: Vec<Duration> = Vec::with_capacity(iters);
        for _ in 0..iters {
            let mut backing: Vec<u8> = Vec::new();
            let t0 = Instant::now();
            write_block_header(&mut backing, &cols).unwrap();
            write_results(&mut backing, &results, shape).unwrap();
            timings.push(t0.elapsed());
        }
        report("Vec<u8> (cold, grow)", &mut timings);
    }
}
