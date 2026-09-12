# Cloud task sandbox (dev-stack VM)

Applies only inside a PostHog Tasks cloud run, on the prebaked `posthog-dev-stack` VM image.
Local developers and CI are unaffected by everything on this page.
`POSTHOG_TASK_RUN_ID` is set in that environment.

Sandboxes using this image receive at least 32 GiB of RAM, including when automatic preview startup is disabled.
Memory overrides above 32 GiB are preserved; lower overrides are raised to 32 GiB.

## Booting the stack

Run `bootstrap-dev-stack` first — it restores the compose host aliases and starts dockerd.
Then `uv sync`, `source .venv/bin/activate`, `hogli start -y -d`, and `hogli wait`.

Always detached. The sandbox has no TTY, and phrocs under a pseudo-TTY grows in memory until the OOM killer takes it.
The detached start returns while the stack is still booting, so `hogli wait` is what blocks until every process is ready.

On user-created runs the backend usually starts the stack itself, to serve the run's preview.
While it does, `hogli start` exits 0 without starting anything, so a second stack cannot starve the VM.
Poll `/tmp/posthog-preview/status.json` until `state` is `ready` or `failed`:

- `ready` — run `hogli wait`. It reports `not reachable` until the backend reaches the phrocs step, so retry it rather than forcing a second start.
- `failed` — the backend does not retry. Start the stack yourself with `hogli start -y -d`.

## Frontend work

`pnpm install --frozen-lockfile --prefer-offline` links from the prebaked pnpm store, and Playwright Chromium is preinstalled.
Product and Storybook builds still run from source.

## Tests

Scope every run to what you changed, with `hogli test --changed` or the test files that cover the touched code.
Run a whole module, package, or repo-wide suite at most once, right before you push, and only for a cross-cutting change.
CI runs the full matrix anyway; repeating it here costs minutes per run and floods the agent's context with output.

`hogli test` runs pytest with `-q` in a sandbox. Set `HOGLI_TEST_VERBOSE=1` to stream prints.

The image seeds `test_posthog` and `pytest.ini` already enables `--reuse-db`.
Do not pass `--create-db` or override pytest `addopts` — either one discards the prewarmed schema.

If pytest starts the full migration history, the VM image predates the database seed, or the test database was replaced.
Let that migration finish before retrying. Interrupting it leaves a partial database that the next run must continue migrating.

## Context wiki edits

For a shared-page correction, read the page with `task-context-wiki-page-retrieve`, then send the updated content to `task-context-wiki-page-propose` with the returned `head_sha` as `base_head`.
The server stores an immutable suggestion without changing the published wiki.
The user must review the full diff before applying a suggestion.
The Desktop review interface ships separately, after the backend is deployed.
Until that interface is available, suggestions stay unpublished. Use direct human page editing for immediate corrections.
Only that user with wiki write permission can apply the stored content. Task and loop tokens cannot approve suggestions.
If the wiki changes before approval, publication returns a conflict. Read the page again and submit a new suggestion; never replace the base head to bypass review.

Task runs with `context_layer_internal:write` can propose edits to existing shared Markdown pages under `org/`, `areas/`, and `decisions/`.
Shared pages must not include `channel_id` frontmatter. Suggestions remain outside the published wiki until approval.
Tasks can directly update their own channel page with `task-context-wiki-page-update`.
Instruction files (`AGENTS.md` and `CLAUDE.md`), generated indexes, scripts, and other channels' pages remain protected.
Loops can edit only their configured channel page, and read-only task tokens cannot write wiki content.
Do not grant broader token scopes to work around a denied write.
Ordinary tasks cannot publish commit bundles or use `scripts/publish` to bypass review.
Server-owned nightly maintenance can publish a dated, content-only dream branch. The server verifies an active internal maintenance task in the organization, not just a branch name or token scope.
Direct human page editing remains available.
This review gate applies to server-minted task and loop tokens. Human/API credentials keep their existing permissions.

## Other differences

- `hogli devex:feedback` is a no-op here. Do not run it from a cloud task.
- A `ci:preflight` advisory never needs the stack. Do not boot it only to clear one.
