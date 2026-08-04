# Stack And Login

Use this reference before checkout and before browser QA.

## Stack Readiness

Set:

```bash
BASE_URL="${BASE_URL:-http://localhost:8010}"
STACK_STARTED_BY_AGENT=0
```

Reuse the user's existing setup by default. Do not start, restart, or replace a dev stack just because you are running QA. First check whether PostHog is already reachable at `BASE_URL`.

In PR mode, prefer a stack where the PR's code executes away from the developer's machine - for example a remote devbox serving `BASE_URL` through a forwarded port (the repo's `setting-up-devbox` skill covers provisioning one). Using a stack that runs on the developer's own machine for PR mode needs the explicit approval described in `safety-rules.md`, because it executes the PR author's code locally. Local mode carries no such gate: it tests the developer's own code.

When `.agents/skills/run-posthog/SKILL.md` is present in the repo, read it and use its current readiness checks, phrocs process guidance, and `setup_test`/login recipe as the source of truth. This skill only adds the QA-specific constraints: reuse the user's stack when it is already usable, ask before starting or restarting PostHog, and stop only the stack the agent started.

```bash
curl -sf --max-time 5 "$BASE_URL/_health"
curl -sf --max-time 10 -o /dev/null -w '%{http_code}' "$BASE_URL/"
```

If those checks show the app is reachable, continue. Do not start, restart, replace, or wait on another stack when the existing `BASE_URL` is already usable. If they fail, use available local health checks, for example process-specific phrocs MCP checks when phrocs is already running:

- `mcp__phrocs__get_process_status(process="backend")`
- `mcp__phrocs__get_process_status(process="frontend")`

Reachable is not the same as serving your checkout. `BASE_URL` may be a forward to a remote stack (for example a Coder devbox), and a forwarded stack can lag behind or diverge from the local working tree. Before exercising the diff or mutating state (login, theme changes, seeded data), confirm the stack actually serves the code under test: open a changed surface, check the change is present, and retry briefly when the stack syncs with a delay. Any data seeding must target the stack the browser talks to - a local `manage.py shell` writes to the local database, which is the wrong place when `BASE_URL` is forwarded to a remote stack. Seed on the stack serving `BASE_URL`, or record a coverage gap instead.

If PostHog is not reachable, check user memory/settings and local preferences first, then repo guidance and nearby docs such as `AGENTS.md` for the preferred way to start the stack. Then ask the user how they want to proceed before starting PostHog. If the folder and command are obvious, you may propose that specific startup path, including whether it runs interactively or in the background, but present it as an inference to confirm. If the folder, command, `BASE_URL`, or startup approach is not obvious, ask how and where the user wants the stack run, or whether to use a different `BASE_URL`. Do not mention team-specific env vars unless the user already brought them up.

Ask in chat and stop until the user answers. A sandbox escalation prompt, command approval dialog, or already-approved command prefix is not workflow approval; it only authorizes a command after the user has chosen agent-managed startup.

If the user approves agent-managed startup, run the approved startup path and set `STACK_STARTED_BY_AGENT=1`. If the command fails because the shell is missing repo dependencies or the global command is not on `PATH`, follow repo guidance for the same startup intent, for example a repo-local wrapper or an environment wrapper such as `flox`. Announce the fallback. Ask again before changing checkout, directory, startup mode, deleting lock files, or starting a different stack. Avoid interactive terminal UIs from headless agent sessions unless the user explicitly asks for them. Stop only the stack you started, and only during cleanup or after user approval.

After startup, repeat the app reachability checks from `run-posthog` or, if that skill is unavailable, the minimal checks above. Also query available process checks:

- `mcp__phrocs__get_process_status(process="backend")`
- `mcp__phrocs__get_process_status(process="frontend")`
- Any process directly relevant to the changed surface, for example `mcp` when testing MCP changes.

Continue only when the app is reachable and the required process set is ready. If backend or frontend is not ready, stop before checkout, edits, uploads, comments, or pushes. If other processes look degraded but are unrelated to the QA target, record that in `run-notes.md` and continue only when the target path is usable.

Prefer phrocs MCP logs:

- `mcp__phrocs__get_process_logs(process="backend")`
- `mcp__phrocs__get_process_logs(process="frontend")`

Fallback to repo-local logs under `.posthog/.generated/logs/` only when phrocs MCP is unavailable.

## Login

If a browser test needs realistic data or an isolated workspace, prefer the repo-local `run-posthog` `POST /api/setup_test/organization_with_team/` recipe: call it from the browser page context, then log in from the page context with the returned `user_email` and password `12345678`. Use the returned `team_id` when constructing `/project/{team_id}/...` routes. This is setup for frontend QA, not a standalone backend/API test.

When a dedicated setup workspace is not needed, default to the public PostHog local-dev seed: `test@posthog.com` / `12345678`. These are documented in [`docs/published/handbook/engineering/manual-dev-setup.md`](../../../../docs/published/handbook/engineering/manual-dev-setup.md) and are seeded by `bin/start`. They exist only on dev stacks seeded that way (a laptop stack or a personal devbox), so falling back to them is safe.

The skill parses `--login-username` / `--login-password` from `$ARGUMENTS` into `LOGIN_USERNAME` / `LOGIN_PASSWORD` (see Preconditions). Apply the seed default only if those are still unset after parsing:

```bash
LOGIN_USERNAME="${LOGIN_USERNAME:-test@posthog.com}"
LOGIN_PASSWORD="${LOGIN_PASSWORD:-12345678}"
```

This gives three sources of credentials, in precedence order: chat flag -> env var (if `LOGIN_USERNAME` / `LOGIN_PASSWORD` are already exported in the shell) -> seed default. Fork-rule runs ignore this precedence entirely: they use throwaway credentials only, per `safety-rules.md`. No `_OVERRIDE` / `_EFFECTIVE` indirection needed.

Never print the password. Refer to chat-provided credentials only as "login override provided" in user-facing output.

With browser MCP/tooling:

1. Navigate to `$BASE_URL/login`.
2. If using `setup_test`, run the in-page setup and login fetches from `run-posthog`, then navigate to the route under the returned `team_id`.
3. Otherwise, fill email and password from the effective login values.
4. Submit the form.
5. Wait for a post-login URL matching `**/project/**`.

If login fails or either effective login value is missing, abort, restore the original branch, and do not post a PR comment because QA did not run.
