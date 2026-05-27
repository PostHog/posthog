# Login

Default to the public PostHog local-dev seed: `test@posthog.com` / `12345678`.
These are documented in
[`docs/published/handbook/engineering/manual-dev-setup.md`](../../../docs/published/handbook/engineering/manual-dev-setup.md)
and are seeded by `bin/start`. They only exist on a local stack, so falling
back to them is safe.

The skill parses `--login-username` / `--login-password` from `$ARGUMENTS` into
`LOGIN_USERNAME` / `LOGIN_PASSWORD` (see Preconditions). Apply the seed default
only if those are still unset after parsing:

```bash
LOGIN_USERNAME="${LOGIN_USERNAME:-test@posthog.com}"
LOGIN_PASSWORD="${LOGIN_PASSWORD:-12345678}"
```

This gives three sources of credentials, in precedence order: chat flag -> env
var (if `LOGIN_USERNAME` / `LOGIN_PASSWORD` are already exported in the shell)
-> seed default. No `_OVERRIDE` / `_EFFECTIVE` indirection needed.

Never print the password. Refer to chat-provided credentials only as
"login override provided" in user-facing output.

With Playwright MCP:

1. Navigate to `$BASE_URL/login`.
2. Fill email and password from the effective login values.
3. Submit the form.
4. Wait for a post-login URL matching `**/project/**`.

If login fails or either effective login value is missing, abort, restore the
original branch, and do not post a PR comment because QA did not run.
