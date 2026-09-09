# ClickHouse utility UDFs

This module contains the executable ClickHouse UDFs used by PostHog:

- `JSONDropKeys`
- `JSONCleanPostHogEventProperties`
- `JSONCleanPostHogPersonProperties`
- `JSONCleanPostHogTemporaryProperties`
- `JSONStripEmptyStringsAndNulls`

Run `./scripts/build.sh` to test the module and build Linux amd64 and arm64 binaries into
`posthog/user_scripts`.

Run `./scripts/integration_test.sh` to execute the stateless fixtures against ClickHouse.

See [JSONDropKeys benchmarks](../../docs/internal/json-drop-keys-benchmarks.md) for the
file-based workloads and commands to compare throughput and allocations.

These utility UDFs keep stable, unversioned names. Regenerating the deployment manifest does not
change `UDF_VERSION`, which only switches callers between versioned funnel UDF releases.
