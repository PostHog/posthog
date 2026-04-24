---
title: Linking Sentry as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Sentry
---

The Sentry connector can link data from your Sentry organization into PostHog.

## Creating a Sentry Auth Token

Sentry supports several authentication methods, but for PostHog you should use an **Auth Token**.

1. In Sentry, create a token from your account settings (for internal integrations or personal tokens).
2. Give the token read access for the resources you want to sync.
3. Copy the token and paste it into PostHog when linking your source.

For token setup details, see Sentry's [Authentication docs](https://docs.sentry.io/api/auth/).

Once the syncs are complete, you can start using Sentry data in PostHog.


To link Sentry:

1. Go to the [Data pipeline sources page](https://app.posthog.com/data-management/sources) in PostHog.
2. Click **+ New source** and then click **Link** next to Sentry.
3. In Sentry, create an **Auth Token** and copy it. PostHog currently supports Auth Tokens only.
4. In PostHog, enter your Sentry **Organization slug** and **Auth Token**.
5. Click **Next**, choose the tables you want to sync, and then click **Import**.

## Available datasets and endpoints

The Sentry source currently supports syncing the following datasets and API endpoints:

| Dataset | Endpoint path |
| --- | --- |
| `projects` | `/organizations/{organization_slug}/projects/` |
| `teams` | `/organizations/{organization_slug}/teams/` |
| `members` | `/organizations/{organization_slug}/members/` |
| `releases` | `/organizations/{organization_slug}/releases/` |
| `environments` | `/organizations/{organization_slug}/environments/` |
| `monitors` | `/organizations/{organization_slug}/monitors/` |
| `issues` | `/organizations/{organization_slug}/issues/` |
| `project_events` | `/projects/{organization_slug}/{project_slug}/events/` |
| `project_users` | `/projects/{organization_slug}/{project_slug}/users/` |
| `project_client_keys` | `/projects/{organization_slug}/{project_slug}/keys/` |
| `project_service_hooks` | `/projects/{organization_slug}/{project_slug}/hooks/` |
| `issue_events` | `/issues/{issue_id}/events/` |
| `issue_hashes` | `/issues/{issue_id}/hashes/` |
| `issue_tag_values` | `/issues/{issue_id}/tags/{key}/values/` |

