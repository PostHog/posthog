# Jest test-speed report
`jest` · 3 shards · 8 tests · suites: nodejs

## At a glance
| Metric | Time |
| ---: | --- |
| Jest runner time (sum of shards) | 49.52s |
| Test-body time (sum) | 30.71s |
| Startup + teardown (sum) | 18.81s |
| Slowest individual test | 7.15s |
| Longest shard | junit-nodejs-1.xml (18.42s) |

## All individual tests — slowest first
Every Jest testcase from this run, ordered by duration.
| Duration | Test | File | Shard | Started |
| ---: | --- | --- | --- | --- |
| 7.15s | creates a person from an event | `nodejs/src/ingestion/persons/person.test.ts` | `junit-nodejs-1.xml` | +9.10s |
| 4.45s | does not replay an old event | `nodejs/src/ingestion/events/event.test.ts` | `junit-nodejs-2.xml` | +8.20s |
| 4.40s | writes a session recording chunk | `nodejs/src/ingestion/session-recording/chunks.test.ts` | `junit-nodejs-3.xml` | +7.00s |
| 3.70s | rejects an oversized chunk | `nodejs/src/ingestion/session-recording/chunks.test.ts` | `junit-nodejs-3.xml` | +1.00s |
| 2.84s | uses the project UUID | `nodejs/src/ingestion/persons/person.test.ts` | `junit-nodejs-1.xml` | +5.60s |
| 2.78s | accepts an empty properties object | `nodejs/src/ingestion/events/event.test.ts` | `junit-nodejs-2.xml` | +1.00s |
| 2.72s | keeps distinct IDs separate | `nodejs/src/ingestion/events/event.test.ts` | `junit-nodejs-2.xml` | +4.50s |
| 2.67s | drops invalid properties | `nodejs/src/ingestion/persons/person.test.ts` | `junit-nodejs-1.xml` | +1.00s |

## Shard balance
| Shard | Tests | Jest runner | Test bodies | Startup + teardown |
| ---: | --- | --- | --- | --- |
| `junit-nodejs-1.xml` | 3 | 18.42s | 12.66s | 5.76s |
| `junit-nodejs-2.xml` | 3 | 16.30s | 9.95s | 6.35s |
| `junit-nodejs-3.xml` | 2 | 14.80s | 8.10s | 6.70s |

## Test-time distribution
| Tests | Shard median range | Shard p90 range | Slowest test |
| ---: | --- | --- | --- |
| 8 | 2.72s – 3.70s | 4.40s – 7.15s | 7.15s |

<details>
<summary><strong>Per-file startup + teardown</strong></summary>

Time not billed to an individual test: module imports, setup files, worker boot, and teardown.

| Overhead | File | Shard |
| ---: | --- | --- |
| 6.70s | `nodejs/src/ingestion/session-recording/chunks.test.ts` | `junit-nodejs-3.xml` |
| 6.35s | `nodejs/src/ingestion/events/event.test.ts` | `junit-nodejs-2.xml` |
| 5.76s | `nodejs/src/ingestion/persons/person.test.ts` | `junit-nodejs-1.xml` |

</details>

<details>
<summary><strong>Shard scaling estimate</strong></summary>

Current shard spread: 14.80s – 18.42s (mean 16.51s).

| Shards | Estimated CI time |
| ---: | --- |
| 3 | 4m17s |
| 4 | 4m12s |
| 5 | 4m10s |
| 6 | 4m08s |
| 7 | 4m07s |
| 8 | 4m06s |
| 9 | 4m06s |
| 10 | 4m05s |

Estimate includes the ~4 minute per-shard services, schema, and build cost.

</details>

> Full per-test history is also emitted to OTLP traces (`ci-nodejs` / `ci-frontend`) and the weekly slow-tests report.
