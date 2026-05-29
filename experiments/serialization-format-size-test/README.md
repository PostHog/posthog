# Serialization format size test: JSON vs Protobuf vs Avro

A small Rust harness that compares the **uncompressed** serialized message size of
JSON, Protobuf and Avro for the `ClickHouseEvent` schema (see `nodejs/src/types.ts`).

The interesting variable is the event's "moderately large" property maps
(`properties`, `person_properties`, `group{0..4}_properties`). In typed wire
formats these can be modelled two ways, both measured here:

- **`-map`** — a native `map<string,string>` (values stringified)
- **`-bytes`** — the map's canonical JSON stored in a single `bytes` field
  (this is how ClickHouse stores `properties` today: a JSON `String` column)

## Running

```bash
cd experiments/serialization-format-size-test
cargo run --release
```

No `protoc` needed — Protobuf messages are defined with `prost`'s derive macros.
Avro sizes use the raw `to_avro_datum()` encoding (no Object Container header).
10,000 events are generated with a fixed seed, payloads log-uniformly spanning
~500 B to ~400 KB (the bulk lives in `properties`).

## Results (10k events, fixed seed)

| format | total | mean | min | p50 | p90 | max | vs json |
|---|--:|--:|--:|--:|--:|--:|--:|
| json | 584.86 MiB | 59.89 KiB | 798 B | 14.61 KiB | 207.73 KiB | 391.07 KiB | 100.0% |
| protobuf-map | 584.09 MiB | 59.81 KiB | 371 B | 14.18 KiB | 208.52 KiB | 393.13 KiB | 99.9% |
| protobuf-bytes | 579.62 MiB | 59.35 KiB | 396 B | 14.03 KiB | 207.16 KiB | 390.48 KiB | 99.1% |
| avro-map | 569.90 MiB | 58.36 KiB | 346 B | 12.95 KiB | 205.22 KiB | 386.94 KiB | 97.4% |
| avro-bytes | 579.13 MiB | 59.30 KiB | 369 B | 13.97 KiB | 207.10 KiB | 390.44 KiB | 99.0% |

Mean bytes per event, bucketed by JSON payload size:

| bucket | count | json | protobuf-map | protobuf-bytes | avro-map | avro-bytes |
|---|--:|--:|--:|--:|--:|--:|
| < 2 KB | 1838 | 1.30 KiB | 915 B | 934 B | **830 B** | 902 B |
| 2–32 KB | 4364 | 10.76 KiB | 10.29 KiB | 10.20 KiB | **9.48 KiB** | 10.14 KiB |
| 32–128 KB | 2079 | 68.54 KiB | 68.69 KiB | 67.97 KiB | **66.62 KiB** | 67.91 KiB |
| ≥ 128 KB | 1719 | 236.79 KiB | 237.79 KiB | 236.21 KiB | **234.00 KiB** | 236.16 KiB |

## Takeaways

1. **For large, string-heavy event payloads the format barely matters
   uncompressed — all within ~3%.** Once the payload is dominated by the actual
   UTF-8 content of property values, every format stores those bytes verbatim.
   Binary framing only removes structural overhead (field names, quotes,
   punctuation), a tiny fraction of a 200 KB event.

2. **The binary-format win is concentrated in small events.** At < 2 KB, avro-map
   is ~36% smaller than JSON and protobuf ~30% smaller, because field framing is a
   large share of a small message. The advantage decays toward 0% as payload grows.

3. **Avro is the most compact**, mainly because it omits field tags/names on the
   wire (schema is external/positional); protobuf still pays 1–2 bytes per field
   tag.

4. **`bytes` vs native `map` is roughly a wash on size** — native maps are even
   slightly smaller than a JSON-bytes blob (the blob re-introduces JSON
   punctuation). Encoding maps as opaque `bytes` is a choice for ingestion
   simplicity / passthrough (no re-parsing, matches ClickHouse's String column),
   not for size savings.

## Caveat

These are **uncompressed** numbers. In production these payloads are LZ4/ZSTD
compressed on Kafka and in ClickHouse, and JSON's repetitive structural tokens
and repeated key names compress very well — typically erasing most of even the
small-event advantage. If wire/storage size is the real concern, the
decision-relevant comparison is post-compression, which this harness does not
measure yet.
