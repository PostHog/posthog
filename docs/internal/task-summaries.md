# Task summaries

`POST /api/projects/{project_id}/tasks/summaries/` returns summaries for the requested task IDs.
The response is paginated. Follow `next` with the same request body to load the remaining summaries.
Task visibility and project boundaries apply to every request.

`latest_run` is null when a task has no runs. Otherwise, it includes two nullable PR fields:

- `pr_url`: the PR URL recorded in the latest run, or null when no non-empty string URL is recorded.
- `pr_state`: `open`, `draft`, `closed`, `merged`, or `unknown`. This field is null when `pr_url` is null.

The run's `pr_merged` flag takes precedence over its recorded `pr_state`.
A PR with a missing or unrecognized state returns `unknown`.
The response excludes other run output, including generated summaries.
These fields describe the latest run only. They do not include PRs from earlier runs.

The batch query selects these fields with the run status. It does not load each run separately.
Each request reads current stored output. PR output can change without a change to the task's `updated_at` value.
The endpoint does not fetch live state from GitHub.

Deploy this backend change before a client relies on the new fields.
Clients that support older servers must retain their task-detail fallback when the PR fields are absent.
