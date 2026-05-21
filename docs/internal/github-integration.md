# GitHub integration

PostHog has three GitHub-flavoured paths that frequently get conflated.
This document is the engineering reference for the main one (the
GitHub App integration) plus a short tour of the two adjacent paths
(social login and the data warehouse source).

Out of scope: the GitHub secret-scanning relay
(`POST /api/alerts/github`, see `posthog/api/github.py`) and any
proposed refactors. This is a state dump of what exists today.

## Overview

| Path | Backed by | Stored as | Used for |
|---|---|---|---|
| **GitHub App integration** | One GitHub App (App + user-to-server tokens) | `Integration` (team) / `UserIntegration` (user), both `kind="github"` | Repo reads, PR comments, issues, commit attribution, agent sandboxes |
| **GitHub OAuth App (social login)** | A separate OAuth App | `UserSocialAuth` (python-social-auth) | "Log in with GitHub" only |
| **Data warehouse GitHub source** | User-supplied PAT | `ExternalDataSource.job_inputs` | Importing issues/PRs/commits as warehouse tables |

Decision guide:

- Editing the integration card under Settings → Integrations, the personal
  integrations page, or anything that calls `api.github.com` on a
  team's behalf? You want the **GitHub App integration**.
- Editing the "Log in with GitHub" button or the SSO pipeline? You want
  the **GitHub OAuth App**.
- Editing a data warehouse pipeline that pulls GitHub data into
  ClickHouse? You want the **data warehouse source**. The App credentials
  are not involved.

## GitHub App integration

### Credentials and settings

| Name | Static/dynamic | Source | Purpose |
|---|---|---|---|
| `GITHUB_APP_CLIENT_ID` | static env | `posthog/settings/integrations.py:36` | JWT `iss` and OAuth `client_id` (same App for both) |
| `GITHUB_APP_PRIVATE_KEY` | static env | `posthog/settings/integrations.py:37` | RS256 PEM for App JWTs. Newlines may be `\n` literals; decoded at sign time. |
| `GITHUB_APP_CLIENT_SECRET` | static env | `posthog/settings/integrations.py:42` | OAuth user-to-server code exchange. Generated in the App's settings once "Request user authorization during installation" is enabled. |
| `GITHUB_APP_SLUG` | dynamic instance setting | `posthog/settings/dynamic_settings.py:128` | Builds `https://github.com/apps/{slug}/installations/new`. Overrideable via `/api/instance_settings/`. |
| `GITHUB_WEBHOOK_SECRET` | dynamic instance setting (masked) | `posthog/settings/dynamic_settings.py:212` | HMAC-SHA256 secret for incoming webhooks. Stored masked. |

There is no GitHub App manifest in this repo. The App must be created
by hand at `github.com/settings/apps`. Required permissions and events
are documented in [GitHub-side App configuration](#github-side-app-configuration).

There is also a `GITHUB_TOKEN` env var (`posthog/settings/__init__.py:98`).
This is a plain PAT used only for plugin repo fetches and the error
tracking public-repo code-search fallback. It is *not* part of the
integration flow and is never written to or read from an `Integration`
row.

### Models

#### `Integration` (team-scoped) — `posthog/models/integration.py:146`

Generic integration row, used for many kinds (Slack, Linear, Email,
Twilio, ...). For `kind="github"`:

- `integration_id` — the GitHub App installation ID
- `config` (JSON) — `installation_id`, `expires_in`, `refreshed_at`,
  `repository_selection`, `account`, `connecting_user_github_login`
- `sensitive_config` (encrypted JSON) — `{ "access_token": "ghs_…" }`
- `repository_cache` / `repository_cache_updated_at` — cached repo
  list, deferred from default queries (`integration.py:200,246`)

#### `UserIntegration` (user-scoped) — `posthog/models/user_integration.py:31`

User-scoped equivalent. Unique on `(user, kind, integration_id)`, so
one row per `(user, installation)` pair — a user can link multiple
installations (personal + several orgs). For `kind="github"`:

- `integration_id` — installation ID (same shape as team-side)
- `config` — installation metadata plus `github_user`
  (`{login, id}`), `user_access_token_expires_at`,
  `user_refresh_token_expires_at`, `user_token_refreshed_at`
- `sensitive_config` — `access_token` (installation token, identical
  semantics to team-side) **plus** `user_access_token` and
  `user_refresh_token` (the OAuth user-to-server pair)

#### `GitHubIntegrationBase` — `posthog/models/github_integration_base.py`

Shared base class for both team and user paths. Notable members:

| Member | Location | What it does |
|---|---|---|
| `client_request(endpoint, method)` | `:98` | Mints an RS256 App JWT (`iss=GITHUB_APP_CLIENT_ID`, ±5min) and calls `https://api.github.com/app/{endpoint}` |
| `verify_user_installation_access(installation_id, user_access_token)` | `:139` | `GET /user/installations/{id}/repositories` — IDOR guard |
| `refresh_access_token()` | `:270` | `POST /app/installations/{id}/access_tokens`. Half-TTL refresh; one 401 retry per call. |
| `list_teams(search, limit, offset)` | `:405` | `GET /orgs/{org}/teams` |
| `list_repositories(page, per_page)` | `:601` | `GET /installation/repositories` |
| `list_branches(repo, limit, offset)` | `:741` | `GET /repos/{owner}/{repo}/branches` |
| `get_default_branch(repository)` | `:927` | `GET /repos/{owner}/{repo}`, Redis-cached for `GITHUB_DEFAULT_BRANCH_CACHE_TTL_SECONDS` (6h, `integration.py:2253`) |
| `_gh_api_get(path, endpoint, timeout)` | `:1210` | Generic authenticated GET. One automatic retry on transient 5xx; raises `GitHubIntegrationError(is_rate_limit=True)` on 403/429 with `X-RateLimit-Remaining: 0` or "secondary rate limit" in the body. |

Prometheus metrics (`github_integration_base.py:29-49`):
`github_integration_api_requests`,
`github_integration_api_rate_limit_remaining`,
`github_integration_api_rate_limit_limit`,
`github_integration_api_rate_limit_reset_timestamp_seconds`,
`github_integration_cache_accesses`.

#### `GitHubIntegration` (team helper) — `posthog/models/integration.py:2336`

Wraps a team `Integration`. Key entry points:

- `integration_from_installation_id(installation_id, team_id, created_by)`
  (`:2340`) — mints an installation token via `client_request` and
  `update_or_create`s the team row.
- `github_user_from_code(code, redirect_uri=None)` (`:2382`) —
  exchanges an OAuth code at `https://github.com/login/oauth/access_token`,
  returns a `GitHubUserAuthorization` (user access token + login + id).
- `first_for_team_repository(team_id, repository)` (`:2454`) — walks
  the team's GitHub integrations and returns the first one whose
  installation token can reach `owner/repo`.
- `create_issue(config)` (`:2485`) — `POST /repos/{org}/{repo}/issues`.

#### `UserGitHubIntegration` (user helper) — `posthog/models/user_integration.py:67`

Wraps a `UserIntegration`. Inherits the App-level token machinery from
`GitHubIntegrationBase`, and adds the user-to-server token machinery:

- `refresh_user_access_token()` (`:187`) — `POST
  /login/oauth/access_token` with `grant_type=refresh_token`. On
  GitHub error codes in `_GITHUB_UNRECOVERABLE_REFRESH_ERRORS`
  (`bad_refresh_token`, `refresh_token_expired`,
  `unauthorized_client`, `user_integration.py:24`), deletes the row
  and raises `ReauthorizationRequired`.
- `get_usable_user_access_token()` (`:227`) — returns the user-to-server
  token, refreshing if past the expiry. The "good" entry point — every
  caller of the user token goes through this.
- `coauthor_trailer` (`:142`) — produces the
  `Co-authored-by: login <id+login@users.noreply.github.com>` trailer
  for git commits made by the agent on the user's behalf.
- `user_github_integration_from_installation(user, installation, authorization, create_only)`
  (`:286`) — module-level factory used by both the team install
  callback (auto-link path) and the personal install callback.

### Token architecture

Three token types, all minted off the same GitHub App:

| Type | Stored | How minted | How refreshed | Used for |
|---|---|---|---|---|
| App JWT (`Bearer ey…`) | never stored | `client_request()` re-signs per call (RS256, ±5 min) | re-minted on demand | `/app/installations/*` only |
| Installation token (`ghs_…`) | `sensitive_config.access_token` on both models | `POST /app/installations/{id}/access_tokens` | `refresh_access_token()`: half-TTL refresh + 401 retry, max 2 attempts | All repo, branch, commit, PR, issue, status, contents API calls |
| User-to-server (`ghu_…`) | `UserIntegration.sensitive_config.user_access_token` (+ refresh token alongside) | OAuth code exchange at `github.com/login/oauth/access_token` | `refresh_user_access_token()` with `grant_type=refresh_token` | User-identity attribution: commit `Co-authored-by`, PR authorship in the agent sandbox |

### Install and OAuth flows

#### Team install (full flow)

1. User clicks "Connect organization" in Settings → Integrations.
   Frontend calls `api.integrations.authorizeUrl({ kind: 'github' })`
   → `GET /api/environments/{team_id}/integrations/authorize?kind=github`.
2. `IntegrationViewSet.authorize` (`posthog/api/integration.py:698`)
   generates a 33-byte state token, stores it in the Django cache at
   `github_state:{user.id}` (5 min TTL), sets a `ph_github_state`
   cookie, and 302s to
   `https://github.com/apps/{GITHUB_APP_SLUG}/installations/new?state=…`.
3. User installs/authorises on GitHub.com.
4. GitHub redirects to `/integrations/github/callback?installation_id=…&code=…&state=…&setup_action=…`.
   Routed by `integrationsLogic.urlToAction`
   (`frontend/src/lib/integrations/integrationsLogic.ts:381`) →
   `handleGithubCallback` (`:187`).
5. `handleGithubCallback` validates `state` against the cookie, then:
   - **Fresh install (has `code`):** `POST
     /api/environments/{team_id}/integrations/` with
     `{kind, config: {installation_id, state, code}}`.
   - **Already installed (no `code` or `setup_action=update`):**
     `POST .../integrations/github/link_existing`, falling back to
     `.../integrations/github/oauth_authorize` if that returns
     `github_link_existing_orphan_installation` or
     `github_link_existing_personal_github_required`.
6. Backend `IntegrationSerializer.create` handles the GitHub branch at
   `posthog/api/integration.py:342`:
   - Validates state vs. cache.
   - `GitHubIntegration.github_user_from_code(code)` to get user identity.
   - `GitHubIntegration.verify_user_installation_access` (IDOR guard).
   - `GitHubIntegration.integration_from_installation_id(...)` creates
     the team `Integration`.
   - Calls `user_github_integration_from_installation(...,
     create_only=True)` (`integration.py:409`) to atomically create a
     `UserIntegration` for the connecting user; an existing personal
     integration is left untouched.

#### Linking an existing installation across teams

`IntegrationViewSet.github_link_existing` —
`posthog/api/integration.py:1093`. Used when an installation is
already attached to a sibling team in the same organization. Requires
the caller's own `UserIntegration` to verify access via
`verify_user_installation_access` before minting a team token. This is
the cross-team escalation guard: project admin alone cannot mint new
team installation tokens; GitHub must confirm the user has access.

#### Orphan installation OAuth

`IntegrationViewSet.github_oauth_authorize` —
`posthog/api/integration.py:1197`. Used when an installation came
through the GitHub-side direct-install path (no `code` in the
redirect). Mints a `https://github.com/login/oauth/authorize` URL so
the user can complete the OAuth half.

#### Personal install

1. User clicks "Connect GitHub" in Settings → Personal integrations.
   Frontend calls
   `POST /api/users/@me/integrations/github/start/`.
2. `UserIntegrationViewSet.github_start`
   (`posthog/api/user_integration.py:372`) generates state, stores it
   under `github_user_install_state:{token}` (10 min TTL), and picks a
   flow:
   - **PostHog Code fast path:** if `connect_from == "posthog_code"`
     and the current team has an installation the user has not yet
     linked, returns a `https://github.com/login/oauth/authorize` URL
     (OAuth-only, no install dance).
   - **Default:** returns
     `https://github.com/apps/{GITHUB_APP_SLUG}/installations/new`.
3. User completes on GitHub.com; GitHub redirects to
   `/complete/github-link/`.
4. `github_link_complete` (`posthog/api/user_integration.py:453`,
   registered at `posthog/urls.py:402`) dispatches on
   `state_payload["flow"]`:
   - default — full App install
   - `oauth_authorize` — team already has installation
   - `oauth_discover` — no installation known; iterates
     `GET /user/installations`
   - `team_oauth_authorize` — orphan install completion that also
     creates the team `Integration`
5. On success, redirects to `/settings/user-personal-integrations?github_link_success=1`,
   or to `/account-connected/github-integration?provider=github` for
   PostHog Code (deep-links into the desktop app via
   `posthog-code://…`).

#### Personal disconnect

`DELETE /api/users/@me/integrations/github/{installation_id}` →
`UserIntegrationViewSet.github_destroy`
(`posthog/api/user_integration.py:274`).

### Webhooks

Entry point in `posthog/urls.py`:

```
opt_slash_path("webhooks/github/pr", github_webhook)   # line 408
opt_slash_path("webhooks/github", github_webhook)      # line 409
```

Both routes resolve to the same `github_webhook` view
(`posthog/urls.py:96`), CSRF-exempt:

1. Reads `GITHUB_WEBHOOK_SECRET` via `get_github_webhook_secret()`
   (`products/tasks/backend/webhooks.py:67`). If unset, returns 500.
2. Verifies the `X-Hub-Signature-256` header with HMAC-SHA256 via
   `verify_github_signature` (`webhooks.py:45`). Mismatch → 403.
3. Parses JSON, dispatches on `X-GitHub-Event`:
   - `issues` / `issue_comment` → `dispatch_github_event`
     (`products/conversations/backend/api/github_events.py:52`). Resolves
     a team from `installation_id` via `_team_for_github_installation`
     (`:23`), then `process_github_event.delay(...)` to Celery
     (multi-region aware proxy).
   - `pull_request` → `handle_pull_request_event`
     (`products/tasks/backend/webhooks.py:73`). Maps `opened` /
     `closed (merged)` / `closed (not merged)` to `pr_created`,
     `pr_merged`, `pr_closed` on a matching `TaskRun`; on merge,
     transitions linked `SignalReport` rows to `RESOLVED`.
   - Any other event → 200 (silent no-op).

The `installation` lifecycle event is **not** handled server-side;
install/uninstall is captured by the OAuth callback and by user-driven
disconnect.

### GitHub-side App configuration

What an operator needs to configure on the App at
`github.com/settings/apps/{slug}`:

- **Webhook URL:** `{SITE_URL}/webhooks/github`
- **User authorisation callback URL:** `{SITE_URL}/complete/github-link/`
  (only one is supported; this single URL must serve both the
  team-install and personal-install flows because both end up at
  GitHub's authorize endpoint and come back via the same path —
  `posthog/urls.py:402`)
- **"Request user authorization (OAuth) during installation":** on
- **Webhook events:** `pull_request`, `issues`, `issue_comment`
- **Repository permissions** (inferred from API calls in the codebase):

| Permission | Level | Required by |
|---|---|---|
| `contents: write` | Repository | Visual review baseline read/commit (`products/visual_review/backend/logic.py`) |
| `statuses: write` | Repository | Visual review commit statuses (`products/visual_review/backend/logic.py`) |
| `pull_requests: write` | Repository | Visual review PR comments (`products/visual_review/backend/logic.py`) |
| `issues: write` | Repository | Conversations issue create (`products/conversations/backend/api/github_setup.py`) and team `create_issue` (`integration.py:2485`) |
| `actions: write` | Repository | Visual review CI rerun (`products/visual_review/backend/logic.py`) |
| `metadata: read` | Repository | Implicit on all repository-scoped tokens |
| `members: read` | Organization | `list_teams` for task assignments (`github_integration_base.py:405`) |

### Project ↔ personal interaction

1. **Auto-link on team install.** When a user installs the App on a
   team, `IntegrationSerializer.create` automatically creates a
   `UserIntegration` for the connecting user with `create_only=True`
   (`posthog/api/integration.py:409`). An existing personal integration
   is preserved.
2. **Cross-team mint requires personal credentials.**
   `github_link_existing` (linking an installation that's already on a
   sibling team) requires the calling user's `UserIntegration` —
   PostHog cannot mint a new team token from another team's metadata
   alone; GitHub must confirm the caller has access
   (`posthog/api/integration.py:1093`).
3. **Agent sandbox token resolution.**
   `get_sandbox_github_token` (`products/tasks/backend/temporal/process_task/utils.py:490`)
   resolves the token to inject into the agent container in this order:
   1. Cached user token from run-create time (legacy CLI callers).
   2. `UserGitHubIntegration.get_usable_user_access_token()` when
      `pr_authorship_mode == PrAuthorshipMode.USER`.
   3. `get_github_token(github_integration_id)` (team installation
      token) for `PrAuthorshipMode.BOT` or when (2) is unavailable.
4. **`GITHUB_TOKEN` is unrelated.** The plain PAT at
   `posthog/settings/__init__.py:98` is used only for plugin repo
   fetches and the error tracking public-repo code-search fallback.
   It never overlaps with `Integration`/`UserIntegration` storage.

### Frontend surface

Settings:

- `frontend/src/scenes/settings/SettingsMap.tsx:1353` — project
  integration card (`integration-github`)
- `:473` — error tracking integration sub-page
- `:1813` — user personal integrations (`personal-integrations`)
- `frontend/src/scenes/settings/environment/Integrations.tsx` —
  `GithubIntegration` component (project connect button)
- `frontend/src/scenes/settings/user/PersonalIntegrations.tsx` —
  personal connection panel
- `frontend/src/scenes/settings/user/personalIntegrationsLogic.ts` —
  personal integration kea logic; reloads on `projectIntegrationsLoaded`
  to surface the auto-linked row

Shared components and logics:

- `frontend/src/lib/integrations/integrationsLogic.ts` — central
  loader; owns the `/integrations/github/callback` handler
- `frontend/src/lib/integrations/githubIntegrationLogic.ts` — paginated
  repo loader keyed on team `integrationId`
- `frontend/src/lib/integrations/userGithubIntegrationLogic.ts` —
  same, keyed on personal `installation_id`
- `frontend/src/lib/integrations/GitHubIntegrationHelpers.tsx` —
  `GitHubRepositoryPicker`, `GitHubRepositorySelectField`
- `frontend/src/lib/integrations/GitHubRepoSummary.tsx` — repo count +
  deep link to `github.com/.../settings/installations/{id}` for repo
  management

Per-product consumers:

| Product | File | What it uses GitHub for |
|---|---|---|
| Error tracking | `frontend/src/lib/components/Errors/Frame/GitProviderFileLink.tsx`, `framesCodeSourceLogic.ts` | "View on GitHub" link from a stack frame; resolves through `api/gitProviderFileLinks/resolve_github` |
| Session replay | `frontend/src/scenes/session-recordings/player/sidebar/PlayerSidebarLinkedIssuesTab.tsx`, `issueFormHelpers.tsx` | Create GitHub issue from a replay |
| Visual review | `products/visual_review/frontend/scenes/VisualReviewSettingsScene.tsx`, `visualReviewSettingsSceneLogic.ts` | Pick repos, configure baselines, toggle PR comments |
| Tasks | `products/tasks/frontend/components/RepositorySelector.tsx`, `taskTrackerSceneLogic.ts` | Pick a repo + installation for an agentic task |
| Conversations | `products/conversations/frontend/scenes/settings/GithubSection.tsx`, `supportSettingsLogic.ts` | Choose which repos to monitor for support tickets |
| Hog functions | `frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts:573`, `CyclotronJobInputIntegrationField.tsx` | "GitHub issue on issue created" sub-template |
| Max AI | `frontend/src/scenes/max/max-constants.tsx:878` | `list_repositories` tool for the `TaskTracker` scene |
| Data modeling | backend-only via `products/data_modeling/backend/models/github_sync_config.py` | dbt-style model sync (frontend surface not yet wired) |
| Account return | `frontend/src/scenes/authentication/AccountConnected.tsx` | Post-OAuth landing; dispatches `posthog-code://integration?…` deep link |

### Repository and branch caching

| Cache | Backed by | TTL | Refresh |
|---|---|---|---|
| Repository list (per integration) | `Integration.repository_cache` JSON column | 1 hour | `POST /api/environments/{team_id}/integrations/{id}/github_repos/refresh` (cooldown `GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS = 30`, `integration.py:2254`) |
| Branch list (per `(integration, repo)`) | Django cache (Redis) | 10 min staleness, 24h eviction | implicit on miss |
| Default branch (per repo) | Django cache (Redis) | 6h (`GITHUB_DEFAULT_BRANCH_CACHE_TTL_SECONDS`, `integration.py:2253`) | implicit on miss |

The repo and `repository_cache_updated_at` columns are `defer()`-ed
from default `Integration` queries (`integration.py:246`) — only
loaded when explicitly read, since `repository_cache` can be large.

## GitHub OAuth App (social login only)

Completely separate from the GitHub App. No `Integration` row, no
webhooks, no `api.github.com` calls beyond identity lookup.

- Credentials (`posthog/settings/web.py:261-263`):
  - `SOCIAL_AUTH_GITHUB_KEY` — client ID
  - `SOCIAL_AUTH_GITHUB_SECRET` — client secret
  - `SOCIAL_AUTH_GITHUB_SCOPE = ["user:email"]`
- Backend: `social_core.backends.github.GithubOAuth2`, registered in
  `AUTHENTICATION_BACKENDS` at `posthog/settings/web.py:218`.
- Callback URL on this OAuth App: `{SITE_URL}/complete/github/` —
  registered by `social_django.urls` (included at
  `posthog/urls.py:403`). The `complete/github-link/` route for the
  App integration is registered on the line above
  (`posthog/urls.py:402`) so the django-social-auth glob does not
  swallow it.
- Tokens stored in `UserSocialAuth` (django-social-auth model) and
  never used to call the GitHub API at runtime.
- The "Log in with GitHub" button is hidden client-side when either
  env var is unset (gated in `posthog/utils.py`).

## Data warehouse GitHub source (user-supplied PAT)

User-driven source for importing GitHub issues / PRs / commits into the
warehouse via the standard data-imports pipeline. Not related to the
App at all.

- User supplies a classic PAT (`ghp_…`) in the warehouse source UI.
- Stored encrypted in
  `ExternalDataSource.job_inputs.auth_method.personal_access_token`.
- Implementation:
  - `posthog/temporal/data_imports/sources/github/source.py` — source
    definition, table discovery, credentials validation.
  - `posthog/temporal/data_imports/sources/github/github.py` — API
    client with `tenacity` retries
    (`retry_if_exception_type(GithubRetryableError)`, exponential
    backoff with jitter).
- No callbacks, no webhooks; purely outbound polling on the temporal
  schedule.

## Local dev caveats

- All `GITHUB_APP_*` env vars are optional in `.env.example`. Absence
  does not break boot. `client_request()` only raises `ValidationError`
  at call time, so the integration UI renders but actions fail.
- `GITHUB_WEBHOOK_SECRET` defaults to `""`. `get_github_webhook_secret()`
  returns `None` and `github_webhook` returns **500** (not 200) on
  incoming events — this is intentional and prevents silent loss of
  webhooks in dev.
- The `SOCIAL_AUTH_GITHUB_*` button is simply hidden if either env var
  is unset.
- Background-agents dev setup walks through populating the four
  `GITHUB_APP_*` keys:
  `products/tasks/backend/management/commands/setup_background_agents.py`.

## Critical file index

Backend — integration core:

- `posthog/settings/integrations.py:36-42` — App env vars
- `posthog/settings/dynamic_settings.py:128,212` — slug, webhook secret
- `posthog/settings/web.py:218,261-263` — social-login backend + creds
- `posthog/settings/__init__.py:98` — `GITHUB_TOKEN` plain PAT
- `posthog/models/integration.py:146` — `Integration` model
- `posthog/models/integration.py:2253-2254` — branch/refresh constants
- `posthog/models/integration.py:2336` — `GitHubIntegration`
- `posthog/models/user_integration.py:31` — `UserIntegration` model
- `posthog/models/user_integration.py:67` — `UserGitHubIntegration`
- `posthog/models/user_integration.py:286` — `user_github_integration_from_installation`
- `posthog/models/github_integration_base.py` — shared App/API helpers

Backend — API surface:

- `posthog/api/integration.py:301` — `IntegrationSerializer.create`
  (GitHub branch at `:342`, auto-link at `:409`)
- `posthog/api/integration.py:698` — team `authorize` action
- `posthog/api/integration.py:1077` — `github_repos`
- `posthog/api/integration.py:1093` — `github_link_existing`
- `posthog/api/integration.py:1197` — `github_oauth_authorize`
- `posthog/api/integration.py:1246` — `refresh_github_repos`
- `posthog/api/user_integration.py:200` — `UserIntegrationViewSet`
- `posthog/api/user_integration.py:274,289,313,333` — destroy /
  repos / repos refresh / branches
- `posthog/api/user_integration.py:372` — `github_start`
- `posthog/api/user_integration.py:453` — `github_link_complete`

Webhooks and routing:

- `posthog/urls.py:96` — `github_webhook` dispatcher
- `posthog/urls.py:402` — `complete/github-link/`
- `posthog/urls.py:408-409` — webhook routes
- `products/tasks/backend/webhooks.py:45,67,73` — signature, secret
  getter, PR handler
- `products/conversations/backend/api/github_events.py:23,52` —
  conversations event router

Product consumers:

- `products/tasks/backend/temporal/process_task/utils.py:490` —
  `get_sandbox_github_token`
- `products/conversations/backend/api/github_setup.py` — conversations
  GitHub channel setup
- `products/visual_review/backend/logic.py` — visual review (cites for
  `contents`, `statuses`, `pull_requests`, `actions` permissions)
- `products/visual_review/backend/github.py` — visual review API wrapper
- `posthog/temporal/data_imports/sources/github/source.py` — warehouse
  source

Frontend:

- `frontend/src/lib/integrations/integrationsLogic.ts:187,381` —
  GitHub callback handling
- `frontend/src/lib/integrations/githubIntegrationLogic.ts`
- `frontend/src/lib/integrations/userGithubIntegrationLogic.ts`
- `frontend/src/lib/integrations/GitHubIntegrationHelpers.tsx`
- `frontend/src/lib/integrations/GitHubRepoSummary.tsx`
- `frontend/src/scenes/settings/SettingsMap.tsx:473,1353,1813`
- `frontend/src/scenes/settings/environment/Integrations.tsx`
- `frontend/src/scenes/settings/user/PersonalIntegrations.tsx`
- `frontend/src/scenes/settings/user/personalIntegrationsLogic.ts`
- `frontend/src/scenes/authentication/AccountConnected.tsx`
