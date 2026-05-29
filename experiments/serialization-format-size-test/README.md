# Serialization format & compression size test

A Rust harness that measures, on the same 10k synthetic events, both:

1. **Uncompressed serialized size** across JSON, MessagePack, Protobuf and Avro
   for the `ClickHouseEvent` schema (see `nodejs/src/types.ts`), and
2. **Compression** of the payload with the algorithms Kafka natively supports
   (gzip, snappy, lz4, zstd) plus brotli as a reference.

Motivation: when a Kafka provider bills on **uncompressed** bytes, wire/transport
compression doesn't lower the bill, so the question is whether a different
serialization format — or application-level compression — meaningfully shrinks
the envelope.

The interesting variable is the event's "moderately large" property maps
(`properties`, `person_properties`, `group{0..4}_properties`). In typed wire
formats these can be modelled two ways, both measured:

- **`-map`** — a native `map<string,string>` (values stringified)
- **`-bytes`** — the map's canonical JSON stored in one `bytes` field (how
  ClickHouse stores `properties` today: a JSON `String` column)

MessagePack is included as the **schemaless binary** option: binary compactness
with the *same dynamic shape as JSON* and **no shared schema / registry / codegen**
— relevant when many producers and consumers span multiple languages.

## Running

```bash
cd experiments/serialization-format-size-test
cargo run --release
```

No `protoc` needed — Protobuf messages use `prost`'s derive macros. Avro sizes use
the raw `to_avro_datum()` encoding (no Object Container header). 10k events are
generated with a fixed seed, payloads log-uniformly spanning ~500 B to ~400 KB.
Property values are drawn from a realistic token corpus (URLs, UAs, enum-ish
strings) with reused keys, so compression behaves like production data rather than
incompressible random noise.

## Results

### 1. Uncompressed size

| format | total | mean | vs json |
|---|--:|--:|--:|
| json | 572.39 MiB | 58.61 KiB | 100.0% |
| msgpack | 558.40 MiB | 57.18 KiB | 97.6% |
| protobuf-map | 571.38 MiB | 58.51 KiB | 99.8% |
| protobuf-bytes | 567.14 MiB | 58.07 KiB | 99.1% |
| avro-map | 558.05 MiB | 57.14 KiB | 97.5% |
| avro-bytes | 566.65 MiB | 58.02 KiB | 99.0% |

Mean bytes per event, bucketed by JSON payload size:

| bucket | count | json | msgpack | protobuf-map | protobuf-bytes | avro-map | avro-bytes |
|---|--:|--:|--:|--:|--:|--:|--:|
| < 2 KB | 1796 | 1.31 KiB | 1.13 KiB | 927 B | 947 B | **848 B** | 916 B |
| 2–32 KB | 4448 | 10.84 KiB | 9.82 KiB | 10.35 KiB | 10.27 KiB | **9.62 KiB** | 10.22 KiB |
| 32–128 KB | 2096 | 69.68 KiB | 67.57 KiB | 69.82 KiB | 69.11 KiB | **67.82 KiB** | 69.05 KiB |
| ≥ 128 KB | 1660 | 234.64 KiB | 231.60 KiB | 235.59 KiB | 234.07 KiB | **231.93 KiB** | 234.01 KiB |

**All formats are within ~2.5% uncompressed.** Because the payload is dominated by
the actual UTF-8 of property keys + values — and the keys are dynamic, so every
format (including a protobuf/avro `map`) stores them as strings — there is no
structural win to be had on large events. The binary advantage only shows on small
events (avro/msgpack ~13–35% smaller at <2 KB) and decays toward 0 as payload grows.

### 2. Compression (per-message — the app-level-compression scenario)

JSON payload, all 10k events:

| codec | total | ratio | comp MB/s | decomp MB/s | vs none |
|---|--:|--:|--:|--:|--:|
| lz4 | 212.47 MiB | 2.69× | 340 | 1235 | 37.1% |
| snappy | 198.03 MiB | 2.89× | 401 | 1295 | 34.6% |
| gzip-6 | 137.90 MiB | 4.15× | 26 | 321 | 24.1% |
| zstd-1 | 165.05 MiB | 3.47× | 224 | 638 | 28.8% |
| zstd-3 | 146.77 MiB | 3.90× | 173 | 586 | 25.6% |
| zstd-9 | 137.40 MiB | 4.17× | 28 | 611 | 24.0% |
| brotli-5 | 134.53 MiB | 4.25× | 24 | 236 | 23.5% |

MessagePack compresses to almost exactly the same place (zstd-3 → 3.80×, 26.3% of
none), so it gives no compression edge over JSON.

### 3. Per-message vs Kafka-style batched (JSON, ~1 MiB batches)

| codec | per-message | batched |
|---|--:|--:|
| lz4 | 2.69× | 2.79× |
| zstd-3 | 3.90× | 4.16× |
| zstd-9 | 4.17× | 4.54× |

Kafka compresses per produce-batch, so batching shares redundancy across events and
does a bit better than per-message — the batched column is the realistic ratio if
you rely on Kafka's own `compression.type`.

### 4. Do formats still differ after compression? (zstd-3, per-message)

| format | compressed | vs json |
|---|--:|--:|
| json | 146.77 MiB | 100.0% |
| msgpack | 147.08 MiB | 100.2% |
| protobuf-bytes | 146.01 MiB | 99.5% |
| avro-bytes | 145.50 MiB | 99.1% |

After compression every format converges to within ~1% — **the format choice is
irrelevant once you compress.**

## Takeaways

1. **Switching serialization format saves ~1–2.5% uncompressed and ~0% after
   compression.** Not worth a migration — and especially not worth coordinating a
   schema/registry/codegen change across many producers and consumers in multiple
   languages. The reason is structural: properties are a dynamic-key map, so even a
   typed `map<string,string>` stores every key as a string on the wire.

2. **Compression is the real lever: ~3.9× (zstd-3) up to ~4.5× (zstd-9 batched),
   i.e. 74–78% fewer bytes.** That dwarfs anything format choice can do. If the
   provider bills on the **bytes you hand the producer**, application-level
   compression (produce an already-compressed blob) attacks that metric directly,
   independent of format. Confirm how the provider meters — and whether every
   consumer is code you control (a third-party sink like ClickHouse's Kafka engine
   can't decompress an app-compressed payload).

3. **Algorithm pick:** **zstd-3** is the sweet spot — 3.9× at ~173 MB/s compress /
   ~586 MB/s decompress. zstd-9 buys ~7% more ratio at ~6× the compress cost; gzip
   matches zstd-9's ratio but is far slower both ways; brotli-5 wins ratio (4.25×)
   but is the slowest to decompress (236 MB/s); lz4/snappy are fastest (340–400
   MB/s) but only ~2.7–2.9×. For high-volume ingestion, zstd is the clear
   ratio/throughput winner.

4. **If you also want a smaller logical format, MessagePack is the low-risk pick** —
   schemaless, no registry, drop-in for JSON's shape — but it only saves ~2.4%
   uncompressed and nothing after compression, so it isn't a cost lever on its own.

## Caveats

- Ratios depend on data realism. Values here come from a token corpus with reuse;
  real events likely compress *at least* this well (often better with larger
  batches), but your own corpus is the ground truth — point the harness at a sample
  of real payloads to confirm.
- MB/s figures are single-threaded input throughput on this machine; treat them as
  relative, not absolute.
