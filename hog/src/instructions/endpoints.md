# Endpoints as YAML files

An endpoint is a HogQL query PostHog serves at a URL.
hog keeps endpoints as YAML files in the repository, one file per endpoint.

```yaml
name: events-by-type
description: Event count for one event type
query: |-
  SELECT count() FROM events WHERE event = {variables.event_type}
variables:
  - name: event_type
    type: String
    default: $pageview
materialization:
  enabled: true
  schedule: 24hour
```

- A file needs `name`, and a HogQL `query` or a `query_definition`. `description`, `variables` and `materialization` are optional.
- `schedule` is one of `15min`, `30min`, `1hour`, `6hour`, `12hour`, `24hour` or `7day`.
- `endpoints.dir` in `posthog.json` names the folder, so `pull`, `diff` and `push` work without a path.

## Change an endpoint

1. Pull what PostHog has: `hog endpoints pull <name> --yes`, or `hog endpoints pull --all --yes`.
2. Edit the file, or write a new one.
3. Try the query without saving it: `hog endpoints run --file <file> --var 'event_type=$pageview'`.
4. Run `hog endpoints diff` to see how the files differ from PostHog. It exits with code 1 when they differ.
5. Run `hog endpoints push --dry-run` and show the person the changes.
6. Run `hog endpoints push --yes` to save them.

Agents pass `--yes` to `pull` and `push`, because hog can't ask them to confirm.
When `pull` or `push` exits with code 1, the output says why: `problems` lists the files hog couldn't read or write, and for `push`, `plan` marks invalid endpoints and `outcomes` marks the ones that failed to save.
`hog endpoints run <name>` runs an endpoint that PostHog already has.
