---
name: gating-sensitive-actions
description: 'Use when deciding whether an endpoint, settings section, or UI flow should require recent authentication (re-auth), when adding `TimeSensitiveActionPermission` or its exemptions (`time_sensitive_allow_if_only_fields`, `time_sensitive_exclude_actions`, `time_sensitive_allow_actions`), when wrapping a page or settings section in `TimeSensitiveAuthenticationArea`, when an API read returns secret material, or when a write fails with `sensitive_action_required_reauth`. Carries the product decision: reads stay open, only sensitive writes need a fresh session, and the backend enforces it; organization settings are the one area gated on navigation. Covers how the frontend opens the re-auth modal and retries the failed request, and how to test a new gate. Trigger terms: re-auth, reauthenticate, reauthentication, sensitive session, fresh session, sudo mode, step-up, TimeSensitiveActionPermission, TimeSensitiveAuthenticationArea, sensitive_action_required_reauth.'
---

# Gating sensitive actions behind re-authentication

A session cookie that is older than `SESSION_SENSITIVE_ACTIONS_AGE` (2 hours by default) can still read everything, but it cannot do sensitive writes until the user re-authenticates.
This skill says which writes count as sensitive, where the gate goes, and how the UI recovers when a write is refused.

## The decision

These rules are settled. Do not reopen them in a feature PR.

1. **Reads stay open.** Opening a page or loading a list never asks for re-auth. Only an action that changes something sensitive does.
2. **The backend enforces the gate.** A frontend-only gate protects nothing, because anyone with the cookie can call the API directly. If an action is sensitive, its endpoint carries `TimeSensitiveActionPermission`. Adding a frontend gate instead of this is wrong.
3. **The frontend reacts, and does not gate up front.** A write that fails with `sensitive_action_required_reauth` opens the re-auth modal. After the user re-authenticates, the same request is sent again. The user does not repeat the action.
4. **Organization settings are the exception.** The whole organization level of settings is wrapped in `TimeSensitiveAuthenticationArea`, so it prompts on navigation. Keep it like that.
5. **User, project, and environment settings never prompt on navigation.** There is no per-section opt-in. If reading a section feels sensitive, the fix is to stop the read from returning the secret (see below), not to gate the page.
6. **A GET never returns a live secret that already exists.** Return a secret only in the response that creates it: new personal API keys, rolled keys, new backup codes. A later read returns metadata, a masked value, or a count. `two_factor_status` returns `backup_codes_remaining`, not the codes.

## What counts as sensitive

Gate a write when it does one of these:

- It changes how someone signs in or proves who they are: password, email, 2FA, passkeys, backup codes.
- It creates, rolls, or revokes a credential: personal API keys, project secret API keys, OAuth connected apps, personal integrations (GitHub, Slack), personal PostHog connections.
- It ends sessions or deletes the account.
- It changes who can act as the user, or what data is collected about them: allow impersonation, data opt-out.
- It changes organization membership, roles, domains, SSO, or invites.

Do not gate UI preferences and bookkeeping: theme, sidebar layout, navigation items, homepage, current team or organization, product intro flags, hedgehog config, cache refreshes such as `github_repos_refresh`.
Exempt these explicitly, as described in the next section.

## Backend: adding the gate

`TimeSensitiveActionPermission` is in `posthog/permissions.py`. Read it before you change anything. The behavior to know:

- It applies only to `SessionAuthentication`. Personal API keys and OAuth tokens always pass. The desktop app and MCP are therefore not affected.
- Safe methods (GET, HEAD, OPTIONS) always pass.
- If `step_up_required(request.session)` is set, every write is refused and the exemption lists do not apply.
- The default permission is only `IsAuthenticated`. No mixin adds this permission, so a viewset is protected only when it lists `TimeSensitiveActionPermission` in `permission_classes`, or on the action.

Add the permission to the viewset `permission_classes`, then exempt the non-sensitive writes:

| Attribute                             | Use it for                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `time_sensitive_allow_if_only_fields` | A write where every submitted field is a preference (see `UserViewSet`). A pending step-up still blocks it. |
| `time_sensitive_allow_actions`        | Named actions that skip the freshness window. A pending step-up still blocks them.                          |
| `time_sensitive_exclude_actions`      | Named actions that are never sensitive. They skip the step-up check too, so use this only for bookkeeping.  |

References: `posthog/api/user.py` (`UserViewSet`), `posthog/api/personal_api_key.py`, `posthog/api/webauthn.py`, `posthog/api/oauth/connected_apps.py`, `posthog/api/user_integration.py`.

When one viewset serves both personal credentials and team-shared records, gate only the personal ones. `PersonalConnectionRecentAuthPermission` in `posthog/api/integration.py` gates `posthog` connections and leaves team integrations as they were.

If a read returns a secret, change the response to a count or a masked value. Do not gate the read. Update the serializer, run `hogli build:openapi`, and change the frontend to show the secret only from the create response.

## Frontend: what happens on a refused write

- `handleFetch` in `frontend/src/lib/api.ts` sees the 403 with `sensitive_action_required_reauth` and calls `awaitReauthentication()` from `lib/logic/apiStatusLogic.ts`.
- `awaitReauthentication()` opens the modal and resolves to `true` after re-auth or `false` after dismissal. When it is `true`, `handleFetch` sends the request once more and returns that response. When it is `false`, the original error reaches the caller. The global error toast ignores this error code.
- Several requests can wait on one re-auth. Each one settles.
- A wrong password keeps the request waiting, because the modal stays open. Only success or dismissal settles it.

So a feature does not need its own handling. Do not catch `sensitive_action_required_reauth` in a logic, and do not call `checkReauthentication()` before a write that `handleFetch` can retry.
A pre-emptive `checkReauthentication()` is correct only when the flow cannot be retried from the start, for example when it redirects the page before a write can fail.

SSO and social login re-auth run in a popup, so the page and its pending request stay alive.
The popup returns to `/reauth/complete` (`sso_reauth_complete` in `posthog/api/authentication.py`), which reports the outcome on the `posthog-sso-reauth` `BroadcastChannel` and closes.
The channel is used instead of `window.opener`, because our `Cross-Origin-Opener-Policy` cuts the opener link once the popup visits the identity provider.
Each popup carries a random `attempt` ID in `next`, and the page echoes it back. The listener ignores any message that does not match the attempt it started, because anyone can open the completion page.
The popup waits for the opener to acknowledge the message before it closes, with a 2-second fallback, because closing right after posting can drop the message.
SAML stays on the full-page redirect. Its identity provider posts back cross-site without the session cookie, so the backend runs a fresh login that can switch accounts, and a popup would hide that switch and retry the write as the other account.
When the browser blocks the popup, the modal also falls back to the full-page redirect. Both paths still lose the pending request.

## Testing a new gate

Add the endpoint to the parameterized cases in `TestTimeSensitivePermissions` in `posthog/api/test/test_authentication.py`:

- `test_credential_writes_require_recent_authentication`: a sensitive write returns 403 with `sensitive_action_required_reauth` on a stale session.
- `test_credential_reads_do_not_require_recent_authentication`: a read or an exempt write does not return 403.

The permission runs before the handler, so placeholder IDs in the URL are enough.
The frontend retry is covered in `frontend/src/lib/logic/apiStatusLogic.test.ts`. Do not add a per-feature frontend test for it.

## Checklist

- [ ] The sensitive write has `TimeSensitiveActionPermission`, and the non-sensitive writes on the same viewset are exempt.
- [ ] No GET returns a secret that already exists.
- [ ] No new `TimeSensitiveAuthenticationArea` outside organization settings.
- [ ] The stale-session test cases include the new endpoint.
