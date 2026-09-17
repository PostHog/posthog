# Task summaries

`POST /api/projects/{project_id}/tasks/summaries/` returns summaries for the requested task IDs.
The response is paginated. Follow `next` with the same request body to load the remaining summaries.
Task visibility and project boundaries apply to every request.

`latest_run` is null when a task has no runs. Otherwise, it includes two nullable PR fields:

- `pr_url`: the task's PR URL, or null when the task has no recorded PR.
- `pr_state`: `open`, `draft`, `closed`, `merged`, or `unknown`. This field is null when `pr_url` is null.

The run's `pr_merged` flag takes precedence over its recorded `pr_state`.
A PR with a missing or unrecognized state returns `unknown`.
The response excludes other run output, including generated summaries.

These fields describe the PR the task points at, which is not always one the latest run opened.
A run that opens no PR of its own starts with an empty output, which is what a resume or a
follow-up message produces. These fields then report the most recent run that did open a PR. A run
that opened its own PR reports that one. This matches the `latest_run` the task detail endpoint
returns, so both endpoints answer the same way about the same task.

A URL counts only when it is a non-empty string, recorded under either `pr_url` or `pr_urls`. For a
run that recorded only `pr_urls`, `pr_url` reports the first usable entry.

The batch query selects these fields with the run status, in one subquery for the latest run and one
for the latest run holding a PR. It does not load each run separately.
Each request reads current stored output. PR output can change without a change to the task's `updated_at` value.
The endpoint does not fetch live state from GitHub.

Deploy this backend change before a client relies on the new fields.
Clients that support older servers must retain their task-detail fallback when the PR fields are absent.
