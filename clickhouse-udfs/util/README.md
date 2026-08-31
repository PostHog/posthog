# ClickHouse utility UDFs

This module contains the executable ClickHouse UDFs used by PostHog:

- `JSONDropKeys`
- `JSONCleanPostHogEventProperties`
- `JSONStripEmptyStringsAndNulls`

Run `./scripts/build.sh` to test the module and build Linux amd64 and arm64 binaries into
`posthog/user_scripts`.

Run `./scripts/integration_test.sh` to execute the stateless fixtures against ClickHouse.
