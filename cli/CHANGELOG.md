# posthog-cli

## 0.7.34 — 2026-06-30

### Patch changes

- [889dd51553](https://github.com/PostHog/posthog/commit/889dd5155315fa05b3cb369f3e461c6f51cc61c1) Strip sourceMappingURL comments when deleting uploaded source maps — Thanks @hpouillot!

## 0.7.33 — 2026-06-25

### Patch changes

- [c334e9f9c3](https://github.com/PostHog/posthog/commit/c334e9f9c3c5f733de8b531c9854412ad253cc4d) Mention Go's `-ldflags=-B=gobuildid` when `symbol-sets upload` finds ELF files without a GNU build id, since Go binaries don't emit one by default. — Thanks @cat-ph!
- [b9097541d4](https://github.com/PostHog/posthog/commit/b9097541d446587f1ad9374b77d2c3e78773f60c) Allow explicit sourcemap release uploads to continue when optional Git metadata cannot be read — Thanks @cat-ph!

## 0.7.32 — 2026-06-24

### Patch changes

- [6fb4456e8f](https://github.com/PostHog/posthog/commit/6fb4456e8f9a5048b3db6ceb6d873241e14fe6b8) Fix the CLI release workflow so the Windows (`x86_64-pc-windows-msvc`) build succeeds and ships with each release. — Thanks @cat-ph!

## 0.7.31 — 2026-06-24

### Patch changes

- [dfd1f66a9f](https://github.com/PostHog/posthog/commit/dfd1f66a9f0a5ae4e492887c79921b0692c97d51) Add `symbol-sets upload` for native (ELF) debug symbols: it scans a directory for executables, shared libraries, and `objcopy --only-keep-debug` companions that carry a GNU build id and uploads them to PostHog. — Thanks @cat-ph!

## 0.7.30 — 2026-06-22

### Patch changes

- [d51a877525](https://github.com/PostHog/posthog/commit/d51a8775252d4fd4e35f389e4960a5f23726e429) Handle Git worktrees and packed refs when detecting repository info — Thanks @hpouillot!

## 0.7.29 — 2026-06-19

### Patch changes

- [8c030733b1](https://github.com/PostHog/posthog/commit/8c030733b14ad4281505634ab7c1a21e4128ff51) Quiet agent API discovery commands — Thanks @cvolzer3!

## 0.7.28 — 2026-06-18

### Patch changes

- [f0bb5426d5](https://github.com/PostHog/posthog/commit/f0bb5426d51601a7e39c4d3bcadbe592962ab980) Remove the `posthog-cli api` experimental opt-in and skip unavailable generated tools without warning noise. — Thanks @cvolzer3!

## 0.7.27 — 2026-06-18

### Patch changes

- [7be64cbe1e](https://github.com/PostHog/posthog/commit/7be64cbe1e982e27c1d863146a6268986b7a3ca3) Fix the post-login hint so `posthog-cli login` suggests a valid next command based on the scopes authorized for the generated key. — Thanks @cvolzer3!

## 0.7.26 — 2026-06-18

### Patch changes

- [801e9a763c](https://github.com/PostHog/posthog/commit/801e9a763c5247540106db6740fe71ba6798bd7f) Fix CLI login for agent workflows by adding the Agent CLI preset, using the supported agent scope set, and showing clearer messages about what the generated key can do. — Thanks @cvolzer3!

## 0.7.25 — 2026-06-17

### Patch changes

- [36812957e0](https://github.com/PostHog/posthog/commit/36812957e0b6548a5586d9341f3bcf7450ad0839) Show default values in upload help — Thanks @marandaneto!

## 0.7.24 — 2026-06-16

### Patch changes

- [10af01f66f](https://github.com/PostHog/posthog/commit/10af01f66fad9b230ca925fe4753f6361cd4ca4a) Refresh master before preparing CLI releases — Thanks @cat-ph!
- [ace786f67b](https://github.com/PostHog/posthog/commit/ace786f67bd4d0360bd79e531cfce2d1f3af9bef) Fix API CLI bundle packaging and lookup — Thanks @cvolzer3!

## 0.7.23 — 2026-06-15

### Patch changes

- [8addff91dd](https://github.com/PostHog/posthog/commit/8addff91ddecd46fe135f51403f6bd3c8b36b7b5) Add agentic API tools — Thanks @cvolzer3!

## 0.7.22 — 2026-06-09

### Patch changes

- [08df2e2c49](https://github.com/PostHog/posthog/commit/08df2e2c495b5708d4c2b15461341cde8aa3b778) Handle indexed sourcemaps during upload — Thanks @hpouillot!

## 0.7.21 — 2026-06-05

### Patch changes

- [c3ee0a34e1](https://github.com/PostHog/posthog/commit/c3ee0a34e1134e8697cabe9c69bafb07ccffd28f) Clarify the ProGuard map ID help text. — Thanks @cat-ph!

## 0.7.20 — 2026-06-05

### Patch changes

- [81b679f143](https://github.com/PostHog/posthog/commit/81b679f14324668be61e6a3f55df04a60427ab75) Clarify the Hermes upload help text. — Thanks @cat-ph!

## 0.7.19 — 2026-06-04

### Patch changes

- [51fc41a92dd](https://github.com/PostHog/posthog/commit/51fc41a92dd46c8a6840152b1647dd6da6894cb9) Add help text for the SSL verification flag. — Thanks @cat-ph!
- [867f88d1e9f](https://github.com/PostHog/posthog/commit/867f88d1e9f00b922ff98f8be475f4e2839d8f7b) Clarify the CLI release tag format in the release docs. — Thanks @cat-ph!

## 0.7.18

- fix: rename `--env-file` to `--dotenv-file`. The npm package runs the CLI binary through a `node` wrapper script, and Node has its own built-in `--env-file` flag — so Node intercepted the flag before it reached the binary, failing with `node: .env: not found` for a missing file. `--env-file` still works as an alias for native installs.

## 0.7.17

- fix: treat a missing `--env-file` as a warning instead of a fatal error — the CLI logs that the file wasn't found and falls back to the other credential sources (process env, then stored credentials). A file that exists but can't be read still errors.

## 0.7.16

- feat: add `--dry-run` flag (and `POSTHOG_CLI_DRY_RUN` env var) to skip artifact uploads (sourcemap, dSYM, Hermes, ProGuard) without contacting PostHog or requiring credentials — for CI gates that bundle to catch regressions but must not upload.

## 0.7.15

- fix: make symbol upload retry logs clearer and report failed finalization explicitly.

## 0.7.14

- feat: add `--env-file <PATH>` to load `POSTHOG_CLI_HOST`, `POSTHOG_CLI_API_KEY`, and `POSTHOG_CLI_PROJECT_ID` (and their legacy aliases) from a dotenv-style file when not set in the process environment. Credentials are resolved atomically from a single source (process env first, then the file), so `POSTHOG_CLI_HOST` from the file cannot redirect a key supplied by the process env.

## 0.7.13

- chore: bump `cargo-dist` to 0.32.0; the new npm installer drops the bundled transitive deps that were carrying open CVEs (`axios`, `follow-redirects`, `minimatch`, `brace-expansion`)

## 0.7.12

- feat: add `--skip-on-conflict` to symbol upload commands for keeping existing symbol sets when content differs
- feat: add `--force` to sourcemap, Hermes, and ProGuard uploads for explicit content overwrites

## 0.7.11

- fix: resolve release once in `process` command to avoid race condition when multiple workers run in parallel
- fix: skip synthetic Swift CU names (e.g. `<swift-imported-modules>`) before joining with `comp_dir` so they no longer dominate the project-root prefix and reject real source files

## 0.7.10

- feat: add `symbol-sets download` command to download symbol sets by ID or ref
- feat: add `symbol-sets extract` command for local file extraction
- fix: prevent ZIP path traversal in dSYM extraction
- fix: validate symbol set ID is a UUID before download

## 0.7.9

- feat: warn and skip empty sourcemaps (no mappings/sources/names) during upload to surface bundler misconfigurations instead of silently uploading useless symbol sets

## 0.7.8

- feat: add `--build` flag to all upload commands (hermes, dsym, proguard, sourcemap) via shared ReleaseArgs
- feat: build number packed into version string (`"1.0+42"`) for release uniqueness; UI splits on `+` to display version and build separately

## 0.7.7

- fix: align `dsym upload` release flags with other upload commands by using `--release-name` / `--release-version` (with backward-compatible aliases)
- fix: reuse shared release args in `dsym upload` so release fallback behavior matches other upload commands

## 0.7.5

- fix: stable source bundle for dSYM uploads — CU-anchored prefix filter prevents framework sources from changing the content hash
- fix: thin fat dSYM binaries per arch before zipping so sibling arch rebuilds don't cause content_hash_mismatch
- fix: add `--force` flag to allow overwriting symbol sets whose content has changed

## 0.7.4

- fix: create per-UUID ZIP for dSYM uploads

## 0.7.3

- feat: enable symbol set compression
- fix: fix process command reading from stdin

## 0.7.2

- feat: allow reading files and directories from stdin

## 0.7.1

- feat: track upload started and upload finished events

## 0.7.0

- feat: promote dsym, hermes, and proguard commands from experimental to top-level
- feat: keep backward-compat aliases under `exp` (hidden from help)

## 0.6.2

- fix: endpoints now save to YAML with proper newlines

## 0.6.1

- chore: bump `cargo-dist` version

## 0.6.0

- Add experimental dSYM upload for iOS/macOS crash symbolication

## 0.5.30

- Add experimental dSYM upload for iOS/macOS crash symbolication

## 0.5.29

- chore: introduce env variable `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID` (backwards compatible)

## 0.5.28

- chore: introduce `--release-name` and `--release-version` options (backwards compatible)

## 0.5.27

- fix: only warns on release id mismatch errors

## 0.5.26

- feat: use env variables provided by github actions when available

## 0.5.24

- chore: add endpoints use case to cli auth flow

## 0.5.23

- feat: add experimental commands for endpoints management

## 0.5.22

- feat: add `--project` and `--version` to upload command to define release

## 0.5.20

- chore: add global `--rate-limit` option for Posthog client

## 0.5.19

- chore: upgrade cargo-dist to 0.30.3

## 0.5.18

- fix: fix git info parsing in vercel environment

## 0.5.17

- feat: add --file option to target built files directly

## 0.5.16

- fix: cut a new version for fixing compromised package

## 0.5.15

- Compromised

## 0.5.14

- Fix authentication issue on sourcemap upload

## 0.5.13

- Add `--include` option on sourcemap commands to match specific files inside directory

## 0.5.12

- Bug fixes and improvements

## 0.5.11

- Do not read bundle files as part of hermes sourcemap commands
- Change hermes clone command to take two file paths (for the minified and composed maps respectively)

## 0.5.10

- Add terminal checks for login and query command

## 0.5.9

- Improve error handling from api
- Reduce logs for sourcemap processing

## 0.5.8

- Adding experimental support for proguard mappings

## 0.5.7

- Fix bug where files point to the same sourcemap

## 0.5.6

- Adding experimental support for hermes sourcemaps

## 0.5.5

- When running inject command multiple times, we only update chunk ids when releases are different

## 0.5.4

- Added no fail flag to disable non-zero exit codes on errors.

## 0.5.3

- Add support for ignoring public path prefixes appended by bundlers to sourceMappingURLs when searching for sourcemaps
  associated with minified source code. Does not modify the sourceMappingURL as published.

## 0.5.2

- Fixes a bug where chunks which shared a sourcemap were mishandled, leading to an error during upload in recent versions, and a silent
  failure in older versions. If you're using next, and saw an error message about "duplicate chunk IDs", this fix addresses that issue.

## 0.5.1

- Attempts to reduce impact of previous breaking changes - re-adds `--project` and `--version` arguments to sourcemap upload command, marking them as no longer used

## 0.5.0

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
