# GitHub integration setup

How the GitHub App integration works and what you need to configure to get it
running — both the **GitHub App** side and your **local env**. This package
(`posthog/api/github_callback/`) handles the install/OAuth callbacks that create
the integration records.

## What gets created

There are two integration records, created by two related flows:

| Record                                | Model                                | Created by                                                        | Used by                                        |
| ------------------------------------- | ------------------------------------ | ----------------------------------------------------------------- | ---------------------------------------------- |
| **Team** `Integration(kind="github")` | `posthog/models/integration.py`      | `team_services.create_team_github_integration_from_oauth_code`    | Tasks/Code, signals custom agents, deployments |
| **Personal** `UserIntegration`        | `posthog/models/user_integration.py` | `personal_finish.github_link_complete` (`/complete/github-link/`) | per-user GitHub linking                        |

Both are created from a GitHub App **installation** plus a user-to-server OAuth
**code**. The App-as-App JWT (for installation tokens) is signed in
`github_integration_base.client_request` using the **Client ID as the JWT
issuer** — there is no separate numeric App ID env var.

## GitHub App configuration

Each engineer needs their own dev GitHub App (GitHub → Settings → Developer
Settings → GitHub Apps → New GitHub App). Assuming the default
`SITE_URL=http://localhost:8010` (the Caddy-fronted port you browse — not 8000):

| App field                                                  | Value                                                | Why                                                                                                                                                                                     |
| ---------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Setup URL** (Post installation)                          | `http://localhost:8010/integrations/github/callback` | Where GitHub returns the browser after install (carries `installation_id`). Frontend `integrationsLogic` route → creates the **team** integration. Tick **Redirect on update**.         |
| **Callback URL** (user authorization)                      | `http://localhost:8010/complete/github-link/`        | The **personal** user-link return route (`github_link_complete`).                                                                                                                       |
| **Request user authorization (OAuth) during installation** | ✅ enabled                                           | The team flow exchanges an OAuth `code`; without it, no `code` is returned and creation fails.                                                                                          |
| **Webhook → Active**                                       | ❌ off for local                                     | GitHub can't reach `localhost`. Only needed for inbound events (PR/issue/installation). If enabled, set the same secret as `GITHUB_WEBHOOK_SECRET` and point it at `…/webhooks/github`. |
| **Client secret**                                          | generate one                                         | Required for the OAuth code exchange (`GITHUB_APP_CLIENT_SECRET`).                                                                                                                      |
| **Private key**                                            | generate a `.pem`                                    | App-JWT signing → installation tokens (`GITHUB_APP_PRIVATE_KEY`).                                                                                                                       |

`http://` localhost is fine — the callback flow uses `SITE_URL` verbatim (no
https rewrite), and a public URL is only required for inbound webhooks. The
install URL is built from the slug:
`https://github.com/apps/{GITHUB_APP_SLUG}/installations/new`, so the slug must
match your App exactly.

### Permissions

| Permission    | Access             | Purpose                                             |
| ------------- | ------------------ | --------------------------------------------------- |
| Metadata      | Read               | Required for all GitHub Apps                        |
| Contents      | Read (R/W to push) | Read files / repo discovery; R/W to create branches |
| Pull requests | Read & Write       | Only if creating/updating PRs                       |

Optional: Issues (R/W), Workflows (R/W).

## Local env (`.env.local`)

Set these to match your App. `.env.local` is loaded by `bin/start` (precedence:
shell env > `.env.local` > `.env.development` > `.env.services`); ad-hoc
`manage.py` runs outside `bin/start` won't have them.

```bash
# OAuth Client ID — starts with Iv1. or Iv23 (NOT the numeric App ID).
# Doubles as the App-JWT issuer, so no separate GITHUB_APP_ID is needed.
GITHUB_APP_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
GITHUB_APP_CLIENT_SECRET=your_client_secret
GITHUB_APP_SLUG=your-app-slug          # URL-friendly name in github.com/apps/<slug>
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Only if you enable the webhook (must match the App's webhook secret):
# GITHUB_WEBHOOK_SECRET=...
```

Literal `\n` in the private key is fine — `client_request` converts them to real
newlines. `GITHUB_APP_SLUG` and `GITHUB_WEBHOOK_SECRET` are instance settings
(env-backed), so they can alternatively be set under instance settings in the DB.

## Connecting (creating the integration record)

Env vars alone create nothing — you must complete the install flow:

1. Start the stack via `bin/start` / `hogli start`.
2. Go to `http://localhost:8010/project/<id>/integrations/github`.
3. Connect **GitHub Integration** → you're sent to
   `github.com/apps/<slug>/installations/new`.
4. Install the App on the account/org that owns your target repos.
5. GitHub returns you to `/integrations/github/callback` with `installation_id`
   - `code`; the frontend POSTs them and the `Integration(kind="github")` row is
     created (and the repository cache begins syncing).

### Connecting a second project to the same org

A GitHub App installs **once per org**, so a second PostHog project in the same
org can't reinstall it: GitHub shows "already configured" and may not redirect
back with a fresh `code`. For that case the GitHub integration settings expose a
**Link existing installation** button (`GithubIntegration` in
`Integrations.tsx`), which POSTs to `integrations/github/link_existing`
(`link_existing_team_github_integration`) and reuses the org's existing
installation without the install redirect. A team admin can link without a
personal GitHub OAuth link; non-admins still need one as an ownership proof (see
`authorize_link_existing_installation`).

## Callback routes

| Route                           | Handler                                               | Flow               |
| ------------------------------- | ----------------------------------------------------- | ------------------ |
| `/integrations/github/callback` | `integrationsLogic` (frontend) → `Integration` create | team integration   |
| `/complete/github-link/`        | `personal_finish.github_link_complete`                | personal user-link |
| `/webhooks/github` (+ `/pr`)    | `posthog/urls.py:github_webhook`                      | inbound events     |

The team code exchange (`team_services`) calls `github_user_from_code(code)`
**without** a `redirect_uri`, so GitHub does not enforce a redirect_uri match on
the token exchange — only the browser landing URL (the App's Setup/Callback URL)
matters.

## Verify / troubleshoot

```bash
# Integration present on a team?
.flox/cache/venv/bin/python manage.py shell -c \
  "from posthog.models.integration import Integration; print(Integration.objects.filter(kind='github').values_list('team_id', flat=True))"
```

| Symptom                                                                             | Likely cause                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Failed to exchange the OAuth code — ensure GITHUB_APP_CLIENT_SECRET is configured` | **Misleading message** — it fires for _any_ failed exchange, not just a missing secret. `team_services` raises it whenever `github_user_from_code()` returns `None`; the real reason is logged as a warning (`code exchange returned no access_token` with GitHub's `error_description`). See the rows below. |
| ↳ GitHub `error: incorrect_client_credentials`                                      | **`GITHUB_APP_CLIENT_ID` holds the numeric App ID, not the OAuth Client ID** (most common), or the client secret is wrong/stale/from a different App. The Client ID starts with `Iv1.`/`Iv23`; the numeric App ID will not work for the token exchange.                                                       |
| ↳ GitHub `error: bad_verification_code`                                             | The OAuth `code` expired (~10 min) or was already used — restart the connect flow to get a fresh one.                                                                                                                                                                                                         |
| `GITHUB_APP_CLIENT_ID is not configured`                                            | Env var unset, or running outside `bin/start`                                                                                                                                                                                                                                                                 |
| Install redirects somewhere wrong / 404                                             | Setup URL not set to `…/integrations/github/callback`                                                                                                                                                                                                                                                         |
| No `code` returned → creation fails                                                 | "Request user authorization during installation" not enabled                                                                                                                                                                                                                                                  |
| Webhook signature verification fails                                                | `GITHUB_WEBHOOK_SECRET` doesn't match the App's webhook secret                                                                                                                                                                                                                                                |
