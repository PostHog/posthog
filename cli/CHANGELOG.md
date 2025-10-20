# posthog-cli

# 0.5.1

- Attempts to reduce impact of previous breaking changes - re-adds `--project` and `--version` arguments to sourcemap upload command, marking them as no longer used

# 0.5.0

- Sourcemap injection, upload and process commands made retriable. Significant improvement to release creation.

## 0.4.8

- fix bug where directory ends with a javascript extension

## 0.4.4

- process uploads in batches

## 0.4.3

- add `ignore` argument to sourcemap inject, upload and process commands
- add `skip_ssl_verification` argument for self-hosted instances

## 0.4.2

- fix url encoded sourcemaps

## 0.4.1

- add remote url to release metadata

## 0.4.0

- extract sourcemap url from source code
- add process command to inject and upload sourcemaps
