---
name: developing-the-cli
description: >
  Changes PostHog's command line in this repo, which ships as two CLIs that must stay in step:
  posthog-cli, the Rust CLI in `cli/`, and hog, its TypeScript successor in `hog/`. Use before
  writing, fixing, or reviewing code under `cli/` or `hog/`, including symbol and sourcemap uploads,
  dSYM, Hermes and ProGuard handling, releases, login and credentials, query, endpoints, and schema
  commands, or a security fix in either CLI. Carries the rule that every change lands in both CLIs,
  how to find the matching code on the other side, the upload parity goldens, and the test and
  release steps for each. Trigger terms: posthog-cli, hog CLI, cli/, hog/, cargo, bun, symbol_sets.rs,
  upload.ts, parity golden, sampo changeset, port to hog.
---

# Developing the CLI

PostHog has two command lines in this repo:

| CLI           | Folder | Language        | Status                                                           |
| ------------- | ------ | --------------- | ---------------------------------------------------------------- |
| `posthog-cli` | `cli/` | Rust            | Published. Customers and the SDK build integrations run it today |
| `hog`         | `hog/` | TypeScript, Bun | Version 1, the successor. Not published yet; see `hog/README.md` |

hog hands the file work of `hog error-tracking` to hog-worker, a Rust program in `hog/worker/` that ships next to the `hog` binary.

Both stay in use until every caller moves to hog, so both must behave the same.

## Change both CLIs

**A change to one CLI is REQUIRED to land in the other one, in the same PR.**
This covers features, bug fixes, error handling, new flags, and security fixes.
A fix that lands only in `cli/` leaves the bug in hog, and the reverse ships a hog that posthog-cli users never get.

The only exceptions are commands that exist on one side:

- hog-only commands, such as `hog setup`, `hog api`, `hog ci` and `hog auth migrate`, have no Rust counterpart.
- `hog/MIGRATING.md` lists the posthog-cli commands that don't come to hog. A change to those touches only `cli/`.

Symbol code is copied, not shared.
A file in `hog/worker/src/` that copies posthog-cli code names its `cli/` source files in its first comment.
A change to one of those `cli/` files must land in the matching `hog/worker/src/` file in the same PR, the reverse too, and `hog/test/parity/` must pass.
A crate that decides a written byte, such as `sourcemap` or `posthog-symbol-data`, is pinned in `hog/worker/Cargo.toml` to its version in `cli/Cargo.lock`, and `hog/test/parity/worker-pins.test.ts` fails until both sides match. Raise both together.

When a change does not apply to the other CLI, say why in the PR description, for example "hog prints only the error message, which never contains the URL".
Reviewers: a PR that touches `cli/src/` or `hog/src/` without the other side, and without that sentence, is incomplete.

## Find the matching code

Port the behavior, not the code. The two CLIs are laid out differently. The one exception is the symbol code in `hog/worker/`, which is copied.

1. Map the command with the table in `hog/MIGRATING.md` (`sourcemap upload` becomes `error-tracking upload`, and so on).
2. Find the hog side with the layout table in `hog/AGENTS.md`. Common pairs:

   | posthog-cli                                                                                          | hog                                                      |
   | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
   | `cli/src/api/symbol_sets.rs` (upload protocol)                                                       | `hog/src/error-tracking/upload.ts`                       |
   | `cli/src/sourcemaps/`, `debug_symbols/`, `dsym/`, `proguard/` (reading, rewriting and packing files) | `hog/worker/src/`, copied                                |
   | The flags, skips, warnings and output of those commands                                              | `hog/src/error-tracking/run.ts`, `pairs.ts`, `native.ts` |
   | `cli/src/release/`, `cli/src/utils/git.rs`                                                           | `hog/src/error-tracking/release.ts`, `git.ts`            |
   | `cli/src/login.rs`                                                                                   | `hog/src/commands/auth/`, `hog/src/posthog/`             |
   | `cli/src/experimental/`                                                                              | `hog/src/commands/query/`, `endpoints/`, `schema/`       |

3. Check how the runtimes differ before copying a fix. For example, reqwest puts the request URL in its error text, while Bun's `fetch` keeps it off `error.message`, so a redaction needed in Rust may not be needed in hog. Verify such a difference, then name it in the PR.

## Follow each side's rules

- hog: read `hog/AGENTS.md` before the first edit. It holds the command, output, error and typed-boundary rules, and the rules for hog-worker and its protocol.
- Uploads: hog must send the same bytes, content hashes and requests as posthog-cli, or re-uploads fail with `content_hash_mismatch`. Read `hog/test/parity/README.md` before changing anything that reaches an upload. When a Rust change alters what posthog-cli uploads, regenerate the goldens from the new binary as that README describes, and review the diff.
- Releases: every user-visible change needs a sampo changeset on each side it touches, in `cli/.sampo/changesets/` (`--package cargo/posthog-cli`) and in `hog/.sampo/changesets/` (`--package npm/hog`). Write it in the pull request, with a sentence that tells users what changed, and rename the file sampo writes after the change. `cli/.sampo/README.md` and the Releases section of `hog/README.md` have the commands.
- hog-worker has no release of its own. The `Release hog` workflow builds it with hog's version and ships both binaries in every archive and package, so a worker change takes a changeset in `hog/.sampo/changesets/`.
- hog release timing: the changeset's file name decides it, because sampo accepts nothing but packages and bumps in the front matter. `weekly-<name>.md` waits for the weekly run on Tuesdays, so use it when the change can wait. Any other name starts a release, which a person approves, when the pull request merges. The `hog changeset` workflow adds `weekly-pr-<number>.md` to a pull request with MCP or catalog changes and no changeset, so those wait for the weekly run too.

## Test both sides

```sh
# posthog-cli
cargo test --locked --manifest-path cli/Cargo.toml
cargo clippy --locked --manifest-path cli/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path cli/Cargo.toml -- --check

# hog. `unit` builds hog-worker first, so it needs a Rust toolchain
pnpm --filter hog unit
pnpm --filter hog typecheck

# hog-worker, from hog/worker/
cargo fmt -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

hog-worker's `cargo test` checks the container goldens. hog's tests and `hog/test/parity/` run the worker through the real CLI, so a worker change is tested there.

Add the regression test on both sides too. hog tests drive the real CLI with `runHog` from `hog/src/testing.ts`, and its `respond` option fakes PostHog and object storage, so a hog test can cover the same failure as the Rust one without a server.
Use `/writing-tests` for both.

## Show the terminal in the PR

A PR that changes what either CLI prints, asks or exits with shows it in the description.
Add a mockup of the terminal for each case that changed: success, each error, and each prompt, as a person at a terminal sees it.
When agent output (`-o json`) changed, show that too.

- Copy the mockup from a real run, such as `pnpm --filter hog hog <command>` or `cargo run --manifest-path cli/Cargo.toml -- <command>`. Write one by hand only for a state you can't reach locally, and say which.
- Put each in a `console` code block that starts with the command, and give the exit code when it isn't 0.
- Every new error code, and every case a review fix adds or changes, gets its mockup in the same push.
- Reviewers judge wording, order and hints from the mockup, so they don't have to check out the branch to see what users get.

## Before you report done

- The PR description shows the terminal for each changed case.
- Both CLIs carry the change, or the PR says why one does not need it.
- Both test suites pass, `hog/test/parity/` is green, and the worker's `cargo fmt`, `cargo clippy` and `cargo test` pass when `hog/worker/` changed.
- A change to posthog-cli's symbol code is copied into `hog/worker/src/`, with the dependency versions equal on both sides.
- `cli/` and `hog/` each have a changeset when their behavior changed.
- Use the `cli` scope in the PR title, as in `fix(cli): ...`, for a change to either CLI.
