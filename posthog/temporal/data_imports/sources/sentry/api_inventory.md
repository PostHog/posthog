# Sentry API inventory for Data warehouse source

This inventory tracks practical read/list Sentry endpoints and how they map to warehouse datasets.
It is intentionally implementation-oriented: it lists grain, keys, pagination, and the initial sync strategy.

## Incremental capability (API time filters)

These endpoints support `start` / `end` / `statsPeriod` query params (ISO-8601); response includes `dateCreated`. We can sync incrementally using `start` and cursor on `dateCreated`:

| Dataset          | API doc                                                                                         |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| `issue_events`   | [List an Issue's Events](https://docs.sentry.io/api/events/list-an-issues-events/)              |
| `project_events` | [List a Project's Error Events](https://docs.sentry.io/api/events/list-a-projects-error-events) |

`issue_hashes`, `issue_tag_values`, and project list endpoints do not expose equivalent time-based filters in the API.

## Implemented datasets

| Dataset                 | Endpoint path                                          | Grain                    | Primary key                            | Pagination                                    | Incremental strategy         | Status      |
| ----------------------- | ------------------------------------------------------ | ------------------------ | -------------------------------------- | --------------------------------------------- | ---------------------------- | ----------- |
| `projects`              | `/organizations/{organization_slug}/projects/`         | organization project     | `id`                                   | Link header cursor                            | full refresh                 | implemented |
| `teams`                 | `/organizations/{organization_slug}/teams/`            | organization team        | `id`                                   | Link header cursor                            | full refresh                 | implemented |
| `members`               | `/organizations/{organization_slug}/members/`          | organization member      | `id`                                   | Link header cursor                            | full refresh                 | implemented |
| `releases`              | `/organizations/{organization_slug}/releases/`         | organization release     | `version`                              | Link header cursor                            | full refresh                 | implemented |
| `environments`          | `/organizations/{organization_slug}/environments/`     | organization environment | `id`                                   | Link header cursor                            | full refresh                 | implemented |
| `monitors`              | `/organizations/{organization_slug}/monitors/`         | organization monitor     | `id`                                   | Link header cursor                            | full refresh                 | implemented |
| `issues`                | `/organizations/{organization_slug}/issues/`           | organization issue       | `id`                                   | Link header cursor                            | incremental on `lastSeen`    | implemented |
| `project_issues`        | `/projects/{organization_slug}/{project_slug}/issues/` | project issue            | composite `project_id + id`            | fan-out from projects + Link header cursor    | full refresh                 | implemented |
| `project_events`        | `/projects/{organization_slug}/{project_slug}/events/` | project event            | composite `project_id + eventID`       | fan-out from projects + Link header cursor    | incremental on `dateCreated` | implemented |
| `project_users`         | `/projects/{organization_slug}/{project_slug}/users/`  | project user             | composite `project_id + id`            | fan-out from projects + Link header cursor    | full refresh                 | implemented |
| `project_client_keys`   | `/projects/{organization_slug}/{project_slug}/keys/`   | project key              | composite `project_id + id`            | fan-out from projects + Link header cursor    | full refresh                 | implemented |
| `project_service_hooks` | `/projects/{organization_slug}/{project_slug}/hooks/`  | project service hook     | composite `project_id + id`            | fan-out from projects + Link header cursor    | full refresh                 | implemented |
| `issue_events`          | `/issues/{issue_id}/events/`                           | issue event              | composite `issue_id + eventID`         | fan-out from issues + Link header cursor      | incremental on `dateCreated` | implemented |
| `issue_hashes`          | `/issues/{issue_id}/hashes/`                           | issue hash               | composite `issue_id + id`              | fan-out from issues + Link header cursor      | full refresh                 | implemented |
| `issue_tag_values`      | `/issues/{issue_id}/tags/{key}/values/`                | issue tag value          | composite `issue_id + tag_key + value` | fan-out from issues/tags + Link header cursor | full refresh                 | implemented |

## Candidate endpoint inventory (future)

### Organization scope

| Candidate dataset          | Endpoint path                                        | Grain                | Key strategy  | Notes                                                   |
| -------------------------- | ---------------------------------------------------- | -------------------- | ------------- | ------------------------------------------------------- |
| `organization_alert_rules` | `/organizations/{organization_slug}/combined-rules/` | org alert rule       | `id`          | Add if endpoint remains stable and list-friendly.       |
| `organization_metrics`     | `/organizations/{organization_slug}/stats_v2/`       | org aggregate metric | composite key | Validate grain and backfill semantics before ingesting. |

### Project scope

| Candidate dataset  | Endpoint path                                            | Grain           | Key strategy               | Notes                                                |
| ------------------ | -------------------------------------------------------- | --------------- | -------------------------- | ---------------------------------------------------- |
| `project_releases` | `/projects/{organization_slug}/{project_slug}/releases/` | project release | `version` or composite key | Evaluate overlap with org-level releases table.      |
| `project_tags`     | `/projects/{organization_slug}/{project_slug}/tags/`     | project tag key | composite key              | Useful as parent inventory for extra fan-out tables. |

### Issue fan-out

| Candidate dataset | Endpoint path                | Grain       | Key strategy  | Notes                                         |
| ----------------- | ---------------------------- | ----------- | ------------- | --------------------------------------------- |
| `issue_owners`    | `/issues/{issue_id}/owners/` | issue owner | composite key | Add if endpoint payload shape remains stable. |

## General mapping rules for future endpoints

- Prefer endpoint-specific keys declared in `settings.py`; do not assume `id` exists.
- Use Link-header cursor pagination as default for Sentry API list endpoints.
- Only enable incremental when the API supports a stable time filter for the selected dataset.
- Add parent identifiers (`organization_slug`, `project_slug`, `issue_id`) in fan-out datasets for deterministic joins.
- Add optional per-endpoint toggles and page caps for high-volume fan-out resources.
- Keep fan-out bounded using source config controls:
  - `max_projects_to_sync`
  - `max_issues_to_fanout`
  - `max_pages_per_parent`
  - `request_timeout_seconds`
  - `max_retries`
