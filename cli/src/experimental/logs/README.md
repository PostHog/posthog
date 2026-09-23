# Importing historical logs from Loki

`posthog-cli exp logs import loki` reads a time range out of Grafana Loki and sends it to PostHog
as OTLP.

Loki guarantees only three things per entry: a nanosecond timestamp, a log line, and a set of
stream labels whose names are arbitrary. It has no schema and no reserved label names. So the
timestamp and the body map themselves, and everything else has to be told, which is what the
config file is for.

## Running it

```sh
export LOKI_USERNAME=123456           # Grafana Cloud instance id
export LOKI_PASSWORD=glc_...          # Grafana Cloud access policy token
export POSTHOG_PROJECT_API_KEY=phc_...

posthog-cli exp logs import loki --config loki-import.yaml --dry-run
posthog-cli exp logs import loki --config loki-import.yaml --checkpoint /data/import.state
```

Self-hosted Loki behind a bearer token uses `LOKI_BEARER_TOKEN` instead of the username and
password. The PostHog host comes from `--host`, or from `posthog-cli login`, so an EU project needs
no extra setting.

`POSTHOG_PROJECT_API_KEY` is the project write key, not a personal API token. The intake rejects a
personal token, and the project key is already public-facing, so a long unattended run never holds
the operator's own credential.

Always run `--dry-run` first. It sizes the job and reports how many sampled records each extraction
rule actually matched. A rule that matches nothing reports `NOT FOUND`, which is the only warning
you get before a run that would otherwise take hours and produce unusable data.

## The config

```yaml
version: 1

source:
  url: https://logs-prod-012.grafana.net
  tenant: prod # X-Scope-OrgID, omit when single-tenant

range:
  from: 2025-03-01T00:00:00Z
  to: 2026-09-01T00:00:00Z
  select:
    - '{namespace="prod"}'

extract:
  service_name: { type: label, name: app }
  severity:
    - { type: json_field, path: level }
    - { type: label, name: level }
  trace_id: { type: structured_metadata, key: trace_id }
  resource_labels: [namespace, app, container]

tuning:
  shard: 1h
  max_records_per_second: 20000
  max_request_bytes: 1500000
```

Extractor types are `label`, `structured_metadata`, `json_field`, `regex` (with a `group`), and
`literal`.

Every field takes either one extractor or a list of them, and the first rule that yields a value
wins. `severity` is the field where that matters most, since a level can sit in a label on some
streams and inside the JSON body on others, but `service_name`, `trace_id`, `span_id` and each
`extra_attributes` entry accept a list on the same terms.

`resource_labels` lists the labels that identify the resource; every other label becomes a
per-record attribute. Omit the key to treat every label as a resource attribute.

Structured metadata needs Loki 3.0 with schema v13 and a writer that sent it. Older data has none,
so `trace_id` rules against it report `NOT FOUND` in a dry run.

### Where the values come from

Your Alloy or Promtail config already answers most of this, in reverse. A `labels` stage that
promoted `level` means `{ type: label, name: level }`; a level left inside a JSON body means
`{ type: json_field, path: level }`. One difference: Alloy stages are an ordered pipeline sharing
an extracted map, while this is a flat per-field mapping, so rules here do not compose.

## Resuming

Progress is recorded per selector after each shard is fully sent. A resumed run re-sends only the
shard it was inside, because the intake assigns record ids at ingest and does not deduplicate, so
an interrupted run cannot avoid that overlap.

Point `--checkpoint` at durable storage. In a Kubernetes Job that means a volume, not the
container filesystem: an evicted pod that loses its checkpoint restarts the whole range.

Widening `range.from` discards the checkpoint and re-imports everything, and says so. Extending
`range.to` forward keeps the progress already made.

## Retention

Imported records take their retention from when they were imported, not from their own timestamp,
so a backfill expires the configured number of retention days after the import finishes.
