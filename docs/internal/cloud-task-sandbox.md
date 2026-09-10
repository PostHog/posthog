# Cloud task sandbox (dev-stack VM)

Applies only inside a PostHog Tasks cloud run, on the prebaked `posthog-dev-stack` VM image.
Local developers and CI are unaffected by everything on this page.
`POSTHOG_TASK_RUN_ID` is set in that environment.

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

## Other differences

- `hogli devex:feedback` is a no-op here. Do not run it from a cloud task.
- A `ci:preflight` advisory never needs the stack. Do not boot it only to clear one.
