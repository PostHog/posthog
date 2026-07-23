# Deploying OAuth app credentials (register → code → charts → secrets)

A PostHog-registered OAuth source (`SourceFieldOauthConfig`, `OAuthMixin`, a new `IntegrationKind`)
needs the OAuth **app** `client_id` / `client_secret` wired through four places. The connector stays
dormant and the OAuth auth method fails closed (`"<Source> app not configured"`) until the last step
lands, so code + charts can merge ahead of the secret values.

Worked example: the Resend source — posthog/posthog **#73107** (code) and PostHog/charts **#13413**
(env wiring).

## 1. Register the OAuth client with the provider

Get a `client_id` / `client_secret` from the provider (their dashboard, or a dynamic-registration API
like Resend's `POST /oauth/register`). Register **all** PostHog callbacks up front — providers pin
`redirect_uri` to an exact match:

- `https://us.posthog.com/integrations/<kind>/callback`
- `https://eu.posthog.com/integrations/<kind>/callback`
- `https://app.dev.posthog.dev/integrations/<kind>/callback`
- `https://localhost:8010/integrations/<kind>/callback` (local, non-ngrok)

One confidential client is reused across all regions, so the same `client_id` / `client_secret` value
goes to every environment. Local ngrok URLs are per-developer and dynamic — a dev who needs ngrok
registers their own throwaway client. The `client_secret` is usually shown once — capture it straight
into the secrets flow below; never commit it.

## 2. Code — declare the env vars

`posthog/settings/integrations.py` (convention: `<SOURCE>_APP_CLIENT_ID` / `<SOURCE>_APP_CLIENT_SECRET`,
empty defaults so the app imports and fails closed when unset):

```python
RESEND_APP_CLIENT_ID = get_from_env("RESEND_APP_CLIENT_ID", "")
RESEND_APP_CLIENT_SECRET = get_from_env("RESEND_APP_CLIENT_SECRET", "")
```

Then wire the `oauth_config_for_kind()` branch (raise `NotImplementedError("<Source> app not configured")`
when either is empty — that's the fail-closed message users see).

## 3. Charts — map env var → secret key (PostHog/charts PR)

Add the two vars in **both** stores, mirroring the existing OAuth apps (Stripe, Salesforce, HubSpot…).
The values are **not** in this repo — only the env-var → AWS-SM-key mapping:

- **`shared/posthog-django/common.yaml`** → `secret_env:` (store `posthog-django-shared-secrets`) — the
  web app runs the OAuth authorize + callback + token exchange, so it needs both vars.
- **`apps/temporal-worker-data-warehouse/values.yaml`** → `secret_env_app_specific:` (store
  `temporal-worker-data-warehouse-secrets`, i.e. the app's `{app-name}-secrets` store) — the sync worker
  re-mints the access token during syncs.

```yaml
# both blocks, keyed name: name (env var: property in the AWS SM secret)
RESEND_APP_CLIENT_ID: RESEND_APP_CLIENT_ID
RESEND_APP_CLIENT_SECRET: RESEND_APP_CLIENT_SECRET
```

Store both the id and the secret as secrets, consistent with `STRIPE_APP_CLIENT_ID` /
`HUBSPOT_APP_CLIENT_ID` in the same blocks. The ArgoCD diff on the PR should show only the two new env
vars on the web app and the data-warehouse worker — nothing else.

## 4. Secrets — write the values into AWS Secrets Manager (PostHog/secrets)

`PostHog/secrets` is a **CLI over AWS Secrets Manager — values are never committed to git.** Use the
bulk `template` command with a **local, uncommitted** YAML file (copy `template-example.yaml`). App-name
keys are the full `-secrets` store names; the same value repeats across environments for one shared
client:

```yaml
secrets:
  posthog-django-shared-secrets:
    RESEND_APP_CLIENT_ID:
      dev: <client_id>
      prod_eu: <client_id>
      prod_us: <client_id>
    RESEND_APP_CLIENT_SECRET:
      dev: <client_secret>
      prod_eu: <client_secret>
      prod_us: <client_secret>
  temporal-worker-data-warehouse-secrets:
    RESEND_APP_CLIENT_ID:
      dev: <client_id>
      prod_eu: <client_id>
      prod_us: <client_id>
    RESEND_APP_CLIENT_SECRET:
      dev: <client_secret>
      prod_eu: <client_secret>
      prod_us: <client_secret>
```

```bash
aws sso login --profile dev        # + prod-eu / prod-us; needs the `secrets-editor` role (/awsaccess in #aws-access)
secrets template --dry-run ./resend.yaml   # preview
secrets template ./resend.yaml             # apply, then delete the local file
```

Notes:

- Adding **keys to existing** secrets (`posthog-django-shared-secrets` already exists) needs no infra
  change. Creating a **brand-new** secret store also needs an EKS-access grant in
  `terraform/modules/eks/external-secrets.tf` (posthog-cloud-infra).
- ExternalSecrets sync from AWS SM to Kubernetes hourly; the CLI offers an immediate Argo force-sync
  after writing (needs the PostHog tailnet), else `kubectl annotate es <name> force-sync=$(date +%s) --overwrite -n posthog`.

## What an agent can and cannot do here

- **Can**: the settings code change; the charts PR (both blocks); register the client if the provider
  has a registration API and the user supplies a provider API key; scaffold the `secrets` template YAML
  with **placeholder** values plus the exact `--dry-run`/apply commands for the human to run.
- **Should not**: run the `secrets template` apply. It needs interactive `aws sso login`, the
  `secrets-editor` AWS role, and the tailnet for the force-sync — and it handles the **live**
  `client_secret`, which must never flow through agent tool output or land in any file (committed or
  scratch). Hand the filled template + commands to the user for that step.
