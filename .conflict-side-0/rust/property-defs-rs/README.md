# Event and property definitions generator (propdefs for short)

This consumes events from `clickhouse_events_json` and writes event and property definitions to postgres. It filters DB updates to avoid duplicate writes (writes are idempotent, but the DB load of writing every property definition every time would be too high).

Hoglets should check out [the runbook](http://runbooks/ingestion/property-defs-rs) for a detailed breakdown of how it's tuned for our current scale, and what metrics to look at and levers to pull if responding to an incident.

## Tests

Tests use sqlx for database interactions. When tests are changed, you need to run in the property-defs-rs directory:

```bash
cargo sqlx prepare -- --tests
```

Then you can run tests using:

```bash
cargo test
```
