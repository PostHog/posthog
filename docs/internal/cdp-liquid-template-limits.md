# Liquid template rendering limits

Hog function and workflow inputs can use tenant-authored Liquid templates. These templates render synchronously in CDP and ingestion Node processes, so every render must have a bounded source size, duration, allocation estimate, and output size.

## Limits

- Template source: 100 KiB across all string values in one input build.
- Render duration: 500 ms across all Liquid strings in one input build.
- LiquidJS allocation estimate: 4 MiB across all Liquid strings in one input build.
- Rendered output: 4 MiB across one input build.

The runtime applies these limits to stored configurations, reruns, and unsaved test configurations. Django also rejects oversized source on create, configuration edits, enable, and publish, including when publishing a restored revision. Disabling or deleting a legacy oversized function remains possible.

## Rollout

The runtime records duration, output size, and limit crossings without recording template content or rendered values. A duration above 100 ms or output above 1 MiB is a soft crossing; the hard limits remain 500 ms and 4 MiB.

After every Node process role has run with the telemetry for seven days, inspect legitimate soft crossings. If none require the extra headroom, lower the hard duration and output limits to 100 ms and 1 MiB.

## Known limits

LiquidJS checks render duration cooperatively between template operations, and its memory limit is an allocation estimate rather than a V8 heap limit. The output emitter checks each chunk before adding it to the result, so repeated static content cannot materialize an oversized output first.
