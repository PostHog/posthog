# posthog-cli

## 0.16.0 — 2026-08-26

### Minor changes

- [db85d262555](https://github.com/PostHog/posthog/commit/db85d262555a61d89eb71b5dfcfc969053b82236) Add `--release-mode` to `hermes clone` and `hermes upload`. `event` leaves the uploaded Hermes source maps release-independent, so a React Native build that ships unchanged JavaScript across two releases keeps one symbol set instead of colliding on the release the first upload stamped on it. Each exception resolves its own release from the `$app_namespace` / `$app_version` / `$app_build` the SDK already sends, so pass `--release-name`, `--release-version` and `--build` matching the app's bundle identifier or applicationId, version and build number. `symbol-set` stays the default. `hermes inject --release-mode=event` no longer errors: it injects content-addressed chunk ids and, unlike a web build, embeds no release id, because a Hermes bytecode bundle has nothing to read one back out. — Thanks @ablaszkiewicz!

## 0.15.1 — 2026-08-24

### Patch changes

- [4c7c1c85604](https://github.com/PostHog/posthog/commit/4c7c1c8560431add076127c3d6bc53ca253aa116) Keep release resolution optional when Info.plist values cannot be resolved — Thanks @marandaneto!

## 0.15.0 — 2026-08-24

### Minor changes

- [30bb8706d09](https://github.com/PostHog/posthog/commit/30bb8706d09854256be3dbe2be6ccd62c8f4a993) Read iOS release metadata from Info.plist files — Thanks @marandaneto!

## 0.14.1 — 2026-08-23

### Patch changes

- [5e488e12013](https://github.com/PostHog/posthog/commit/5e488e120131361723c3b86cc98dcd3d7e814322) Accept sourcemaps that use the camel-case `chunkId` field when cloning or uploading Hermes sourcemaps. — Thanks @marandaneto!

## 0.14.0 — 2026-08-21

### Minor changes

- [7dd3d0f5c27](https://github.com/PostHog/posthog/commit/7dd3d0f5c27b044db02b30ed7af19909010f96a9) With `--release-mode=event`, `sourcemap inject` now adopts a bundler-emitted ECMA-426 debug id (`//# debugId=` comment or the sourcemap's `debugId` field) as the chunk id instead of deriving its own, so one id identifies the chunk across the toolchain. The sourcemap's `debugId` field is preserved on save instead of being renamed to `chunk_id`, a bundler-stamped debug id no longer makes inject skip the mapping adjustment for the injected snippet, and hermes uploads still accept maps that carry only a `debugId`. Behavior change: `sourcemap upload --hermes` now fails with an error when it finds no maps carrying a chunk id or debug id, instead of exiting successfully having uploaded nothing. — Thanks @ablaszkiewicz!

## 0.13.3 — 2026-08-20

### Patch changes

- [ee7d6424091](https://github.com/PostHog/posthog/commit/ee7d642409193f1dd781651c931991a70497712e) Linux release binaries now embed a GNU build id, so native crash reports from the CLI can be matched to uploaded debug symbols. — Thanks @ablaszkiewicz!

## 0.13.2 — 2026-08-20

### Patch changes

- [029c984bdef](https://github.com/PostHog/posthog/commit/029c984bdefc2a09acb7975e29de052fcf0144d7) Retry symbol set uploads through the standard S3 endpoint when the transfer-acceleration endpoint is unreachable, so uploads complete on networks that block the accelerate domain. A 5 second connect timeout on uploads makes unreachable endpoints fail fast. — Thanks @ablaszkiewicz!

## 0.13.1 — 2026-08-20

### Patch changes

- [fd234e17b30](https://github.com/PostHog/posthog/commit/fd234e17b301dcf20ffac31d839a773d400af933) Improve CLI error diagnostics with native stack symbolication metadata, release debug symbols, and structured categories for local file and parsing failures. — Thanks @hpouillot!

## 0.13.0 — 2026-08-18

### Minor changes

- [f0be634b15f](https://github.com/PostHog/posthog/commit/f0be634b15fbf374bf90db01dfbd9023f9db6536) Add `--release-mode` to `proguard upload`, matching `sourcemap upload`. `symbol-set` (the default) keeps stamping the release onto the uploaded mapping. EXPERIMENTAL `event` creates the release but leaves the mapping unbound, so each event resolves its own release from the app version and namespace the SDK already sends. A map id is derived from the mapping's own content, so this keeps one symbol set for a mapping that several releases share. Also settable via `POSTHOG_RELEASE_MODE`. — Thanks @ablaszkiewicz!

## 0.12.0 — 2026-08-18

### Minor changes

- [45016b12515](https://github.com/PostHog/posthog/commit/45016b12515b58f68ad22f1a0c053c39e2fd97b8) Add `posthog-cli release resolve`, which prints the id of the release the current build belongs to and creates the release if it doesn't exist yet. Only the id goes to stdout, so `RELEASE_ID=$(posthog-cli release resolve)` works; `--json` prints the whole release. It resolves the same release `sourcemap inject` would, so a bundler plugin that injects the release id into chunks itself lands on the same row. When nothing identifies a release, it prints nothing and exits `0`. `--dry-run` skips it, since resolving a release can create one. — Thanks @ablaszkiewicz!

### Patch changes

- [90730d20684](https://github.com/PostHog/posthog/commit/90730d206846ba073611c5ed103536ddd2828943) Delete CSS source maps and remove their sourceMappingURL comments after upload — Thanks @marandaneto!

## 0.11.3 — 2026-08-17

### Patch changes

- [617ed9c912a](https://github.com/PostHog/posthog/commit/617ed9c912a432505cb20237bce95a81dde09c6d) Derive the `--release-mode event` chunk id from the minified source alone, and overwrite a symbol set whose content changed instead of failing. Bundlers embed the original file in `sourcesContent`, so a comment-only edit rewrote the sourcemap and, with the map folded into the id, minted a new chunk for code that never changed. The content hash still covers source and map, so that edit re-uploads the chunk under its existing id. Chunk ids injected by earlier versions change once on the next build, which re-uploads those chunks under their new ids. `--skip-on-conflict` is now ignored in this mode, with a warning: every chunk carries the release id in its injected snippet, so every chunk conflicts on every release, and skipping them all would leave the previous release id in place. — Thanks @ablaszkiewicz!

## 0.11.2 — 2026-08-14

### Patch changes

- [751c7c08aa2](https://github.com/PostHog/posthog/commit/751c7c08aa23132834945f86a54e507bd3748bdc) Upload one symbol set per chunk id when processing sourcemaps. In `--release-mode event` a bundler that copies an entry point to a second name (a hashless alias beside `app-<hash>.js`) produces two byte-identical files that share a sourcemap, and so one content-addressed chunk id twice, which the bulk-start endpoint rejects as `invalid_chunk_ids`. — Thanks @ablaszkiewicz!

## 0.11.1 — 2026-08-13

### Patch changes

- [c75bed06227](https://github.com/PostHog/posthog/commit/c75bed062278959c10907d1245c39a0d8ef20d11) Retry transient GitHub release download failures with exponential backoff when installing `@posthog/cli` from npm. — Thanks @marandaneto!

## 0.11.0 — 2026-08-12

### Minor changes

- [8d58ef5de6c](https://github.com/PostHog/posthog/commit/8d58ef5de6c34563ed1c07a54c92fbbfe9e397d4) Add `--release-mode` (env `POSTHOG_RELEASE_MODE`) to `inject`/`upload`/`process`. The default `symbol-set` keeps the existing behavior: the release id is stamped onto the uploaded symbol sets. The experimental `event` mode derives content-addressed chunk ids that stay stable across rebuilds and injects the release id into each JS chunk as `_posthogReleaseId`, so the SDK reports it per event and symbol sets stay release-independent. The release is still created; it just isn't bound to any chunk. — Thanks @ablaszkiewicz!

## 0.10.0 — 2026-08-03

### Minor changes

- [2c588c9673](https://github.com/PostHog/posthog/commit/2c588c967361ba1e0ca39fee67687b5336cbc64b) Add `--no-release-bind` to `dsym upload`: the release is still created, but uploaded symbol sets stay release-independent. — Thanks @ablaszkiewicz!

## 0.9.4 — 2026-07-30

### Patch changes

- [a29315a19c](https://github.com/PostHog/posthog/commit/a29315a19c59003b5160f479bbd452b530f9500d) Sourcemap, dSYM, and ProGuard uploads now end with a single per-run summary line reporting how many chunks were uploaded, skipped as already present on the server, and skipped as too large. The summary is logged even when a run fails partway, and the same counts are attached to the `error_tracking_cli_sourcemaps_upload_finished` telemetry event so skip rates are queryable. — Thanks @ablaszkiewicz!

## 0.9.3 — 2026-07-30

### Patch changes

- [ccd7de59e0](https://github.com/PostHog/posthog/commit/ccd7de59e0399f26ddff1b60acba2a93b3be42a0) Symbol set uploads (`sourcemap upload`, `sourcemap upload-hermes`, `symbol-sets upload`, dSYM and Proguard uploads) are now significantly faster: chunk uploads reuse a single HTTP connection pool instead of opening a fresh TLS connection per chunk, payload content hashes are computed once (in parallel) instead of twice per file, and sourcemap payload preparation (serialization + compression) runs across all cores. — Thanks @hpouillot!

## 0.9.2 — 2026-07-28

### Patch changes

- [d871ba0d38](https://github.com/PostHog/posthog/commit/d871ba0d38042331e19b8426ef09fcf0a375a832) Fixed `posthog-cli api` commands crashing on Windows when loading the bundled Node.js script. — Thanks @cvolzer3!

## 0.9.1 — 2026-07-23

### Patch changes

- [1e49417142](https://github.com/PostHog/posthog/commit/1e49417142febac7925637eeb92ec12549e88235) Publish fresh CLI artifacts after fixing repository paths that prevented the Windows release build from checking out the source. — Thanks @cat-ph!

## 0.9.0 — 2026-07-22

### Minor changes

- [845de8f80c](https://github.com/PostHog/posthog/commit/845de8f80c301e63e7daea1a73a33a6a98cf3a9c) `symbol-sets upload` now accepts standalone Mach-O executables and dylibs, not just ELF files and `.dSYM` bundles. Binaries that embed their own DWARF — Go binaries on macOS, which never produce a dSYM (`dsymutil` reports "no debug symbols in executable") — upload directly, with the `LC_UUID` as the symbol set id. Universal (fat) binaries upload one symbol set per architecture slice. Go's default darwin build compresses the embedded DWARF, which the server cannot read yet; such binaries are skipped with guidance to rebuild with `-ldflags=-compressdwarf=false`. — Thanks @cat-ph!

## 0.8.5 — 2026-07-21

### Patch changes

- [f3a3420b95](https://github.com/PostHog/posthog/commit/f3a3420b951b9a38d75cbc811f44745585e2cba5) `posthog-cli api` failures are now diagnosable and attributable. Launch failures report the specific cause (bundle not embedded in the build, no home directory, install-directory write failure with the underlying IO error kind, Node.js missing) both in the error message and in error telemetry, instead of one generic bundle-not-found error. When the proxied Node process fails, the CLI now exits through its normal path — flushing telemetry and honoring `--no-fail` — instead of terminating immediately, and the bundled API CLI flushes its own analytics before exiting non-zero so failed calls are no longer silently dropped. The `api` command also emits the standard command-run usage event and attaches the project id from `POSTHOG_CLI_PROJECT_ID`/`POSTHOG_CLI_ENV_ID` to telemetry when stored credentials are not used. — Thanks @cvolzer3!

## 0.8.4 — 2026-07-16

### Patch changes

- [f45778f281](https://github.com/PostHog/posthog/commit/f45778f28141b42559f59dca347aa64e8671c8bd) The dotenv credentials file can now also be pointed at with the `POSTHOG_CLI_DOTENV_FILE` environment variable, equivalent to passing `--dotenv-file` — for callers that control the environment but not the command line (e.g. an Xcode build phase invoking the iOS SDK's upload-symbols.sh). — Thanks @ablaszkiewicz!

## 0.8.3 — 2026-07-15

### Patch changes

- [97457ef9b4](https://github.com/PostHog/posthog/commit/97457ef9b493debd3975f12b8b6d1c4baaee2d93) Sourcemap upload concurrency can now be configured with `--concurrency` or `POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY`, while keeping the existing default of 10 uploads at a time. — Thanks @DebadityaHait!

## 0.8.2 — 2026-07-13

### Patch changes

- [e38163eaab](https://github.com/PostHog/posthog/commit/e38163eaab6d1120f3c87fc2c38f2772ee9cadf2) Fix concurrent release creation and multipart symbol uploads — Thanks @ablaszkiewicz!

## 0.8.1 — 2026-07-06

### Minor changes

- [066d914497](https://github.com/PostHog/posthog/commit/066d9144970955eaf366ff2a8be818460c6ad759) `symbol-sets upload` now also accepts Apple `.dSYM` bundles, packaging them through the same path as `dsym upload` (uppercase UUID chunk_ids, `AppleDsym` container). A single `posthog-cli symbol-sets upload --directory <dir>` run uploads both Linux ELF debug symbols and macOS dSYMs, so native symbol uploads no longer need a different command per platform. The dSYM branch shells out to `dwarfdump` (Xcode, macOS-only); when it is unavailable the bundle is reported and skipped while ELF symbols in the same directory still upload. The standalone `dsym upload` command is unchanged. — Thanks @cat-ph!

### Patch changes

- [d57bdcce6d](https://github.com/PostHog/posthog/commit/d57bdcce6dc77adde629de5ffbbad10a6a99b850) Capture CLI errors with PostHog telemetry — Thanks @hpouillot!

## 0.8.0 — 2026-07-03

_Never published: the release pipeline's Windows build failed after the version bump landed, so no tag, GitHub release, or npm package exists for this version. Its changes first shipped in 0.8.1._

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
- [dfd1f66a9f](https://github.com/PostHog/posthog/commit/dfd1f66a9f0a5ae4e492887c79921b0692c97d51) Add `symbol-sets upload` for native (ELF) debug symbols: it scans a directory for executables, shared libraries, and `objcopy --only-keep-debug` companions that carry a GNU build id and uploads them to PostHog. — Thanks @cat-ph!

## 0.7.31 — 2026-06-24

_Never published: the release pipeline's Windows build failed after the version bump landed, so no tag, GitHub release, or npm package exists for this version. Its changes first shipped in 0.7.32._

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
