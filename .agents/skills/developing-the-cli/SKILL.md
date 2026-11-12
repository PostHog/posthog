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

Both stay in use until every caller moves to hog, so both must behave the same.

## Change both CLIs

**A change to one CLI is REQUIRED to land in the other one, in the same PR.**
This covers features, bug fixes, error handling, new flags, and security fixes.
A fix that lands only in `cli/` leaves the bug in hog, and the reverse ships a hog that posthog-cli users never get.

The only exceptions are commands that exist on one side:

- `hog/src/commands/legacy.ts` lists the commands posthog-cli still owns (`logs`, `tasks`, `upgrade`). A change to those touches only `cli/`.
- hog-only commands, such as `hog setup`, `hog api`, `hog ci` and `hog auth migrate`, have no Rust counterpart.
- The "Not planned" list in `hog/README.md` names posthog-cli commands hog will not port.

When a change does not apply to the other CLI, say why in the PR description, for example "hog prints only the error message, which never contains the URL".
Reviewers: a PR that touches `cli/src/` or `hog/src/` without the other side, and without that sentence, is incomplete.

## Find the matching code

Port the behavior, not the code. The two CLIs are laid out differently.

1. Map the command with the table in `hog/MIGRATING.md` (`sourcemap upload` becomes `error-tracking upload`, and so on).
2. Find the hog side with the layout table in `hog/AGENTS.md`. Common pairs:

   | posthog-cli                                     | hog                                                |
   | ----------------------------------------------- | -------------------------------------------------- |
   | `cli/src/api/symbol_sets.rs` (upload protocol)  | `hog/src/error-tracking/upload.ts`                 |
   | `cli/src/sourcemaps/`, `cli/src/debug_symbols/` | `hog/src/error-tracking/kinds/`, `.../native/`     |
   | `cli/src/release/`                              | `hog/src/error-tracking/release.ts`, `git.ts`      |
   | `cli/src/login.rs`                              | `hog/src/commands/auth/`, `hog/src/posthog/`       |
   | `cli/src/experimental/`                         | `hog/src/commands/query/`, `endpoints/`, `schema/` |

3. Check how the runtimes differ before copying a fix. For example, reqwest puts the request URL in its error text, while Bun's `fetch` keeps it off `error.message`, so a redaction needed in Rust may not be needed in hog. Verify such a difference, then name it in the PR.

## Follow each side's rules

- hog: read `hog/AGENTS.md` before the first edit. It holds the command, output, error and typed-boundary rules.
- Uploads: hog must send the same bytes, content hashes and requests as posthog-cli, or re-uploads fail with `content_hash_mismatch`. Read `hog/test/parity/README.md` before changing anything that reaches an upload. When a Rust change alters what posthog-cli uploads, regenerate the goldens from the new binary as that README describes, and review the diff.
- Releases: every user-visible change needs a sampo changeset on each side it touches, in `cli/.sampo/changesets/` (`--package cargo/posthog-cli`) and in `hog/.sampo/changesets/` (`--package npm/@posthog/hog`). A merged changeset starts a release that a person approves. `cli/.sampo/README.md` and the Releases section of `hog/README.md` have the commands.

## Test both sides

```sh
# posthog-cli
cargo test --locked --manifest-path cli/Cargo.toml
cargo clippy --locked --manifest-path cli/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path cli/Cargo.toml -- --check

# hog
pnpm --filter @posthog/hog unit
pnpm --filter @posthog/hog typecheck
```

Add the regression test on both sides too. hog tests drive the real CLI with `runHog` from `hog/src/testing.ts`, and its `respond` option fakes PostHog and object storage, so a hog test can cover the same failure as the Rust one without a server.
Use `/writing-tests` for both.

## Show the terminal in the PR

A PR that changes what either CLI prints, asks or exits with shows it in the description.
Add a mockup of the terminal for each case that changed: success, each error, and each prompt, as a person at a terminal sees it.
When agent output (`-o json`) changed, show that too.

- Copy the mockup from a real run, such as `pnpm --filter @posthog/hog hog <command>` or `cargo run --manifest-path cli/Cargo.toml -- <command>`. Write one by hand only for a state you can't reach locally, and say which.
- Put each in a `console` code block that starts with the command, and give the exit code when it isn't 0.
- Reviewers judge wording, order and hints from the mockup, so they don't have to check out the branch to see what users get.

## Before you report done

- The PR description shows the terminal for each changed case.
- Both CLIs carry the change, or the PR says why one does not need it.
- Both test suites pass, and `hog/test/parity/` is green.
- `cli/` and `hog/` each have a changeset when their behavior changed.
- Use the `cli` scope in the PR title, as in `fix(cli): ...`, for a change to either CLI.
