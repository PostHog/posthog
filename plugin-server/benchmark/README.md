# Plugin Server Benchmark

Synthetic benchmark tools for plugin-server worker threads.

## Setup

```sh
cd plugin-server/benchmark
npm install
```

## Generate Events

```sh
npm run generate-events -- --num-events 10000 --event-size 256 --subsequent-events 10 --format json --output events.jsonl
npm run generate-events -- --num-events 10000 --event-size 256 --subsequent-events 10 --format protobuf --output events.pb
```

Or directly with node:

```sh
node generate-events.js --num-events 10000 --event-size 256 --subsequent-events 10 --format json --output events.jsonl
node generate-events.js --num-events 10000 --event-size 256 --subsequent-events 10 --format protobuf --output events.pb
```

- `--num-events` (required): Number of events to generate
- `--event-size`: Approximate size of the properties object in bytes (default: 256)
- `--subsequent-events`: Number of subsequent events per distinct id (default: 1)
- `--format`: Output format: json or protobuf (default: json)
- `--output` (required): Output file path

Progress is logged to stderr. Output is written to the specified file.

## Run Benchmarks

### Single-threaded
```sh
npm run single-threaded -- --file events.jsonl --loops 10 --format json
npm run single-threaded -- --file events.pb --loops 10 --format protobuf
```

### Multi-threaded
```sh
npm run multi-threaded -- --file events.jsonl --workers 4 --batch-size 100 --loops 10 --format json
npm run multi-threaded -- --file events.pb --workers 4 --batch-size 100 --loops 10 --format protobuf
```

Or directly with node:
```sh
node multi-threaded.js --file events.jsonl --workers 4 --batch-size 100 --loops 10 --format json
node multi-threaded.js --file events.pb --workers 4 --batch-size 100 --loops 10 --format protobuf
```

- `--batch-size`: Number of messages to batch together (default: 100)
- `--loops`: Number of times to process the file (default: 1)
- `--format`: Input format: json or protobuf (default: json)

- `--file` (required): Path to JSONL file
- `--workers`: Number of worker threads (default: 4)

Both benchmarks report progress and message rate every 5 seconds.
