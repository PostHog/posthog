# posthog-cli

# 0.5.7

- Fix bug where files point to the same sourcemap

# 0.5.6

- Adding experimental support for hermes sourcemaps

# 0.5.5

- When running inject command multiple times, we only update chunk ids when releases are different

# 0.5.4

- Added no fail flag to disable non-zero exit codes on errors.

# 0.5.3

- Add support for ignoring public path prefixes appended by bundlers to sourceMappingURLs when searching for sourcemaps
  associated with minified source code. Does not modify the sourceMappingURL as published.

# 0.5.2

- Fixes a bug where chunks which shared a sourcemap were mishandled, leading to an error during upload in recent versions, and a silent
  failure in older versions. If you're using next, and saw an error message about "duplicate chunk IDs", this fix addresses that issue.

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
