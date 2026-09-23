# Self-service event deletion API

The self-service event deletion API lets authorized users submit a HogQL query that selects events for the existing deletion workflow.
The API is available only when the `self-service-data-deletion` feature flag is enabled for the project.

## Authorization

Organization admins can use every endpoint.
Other organization members have no access by default.
An admin can grant a member or role explicit `data_deletion` access through resource access control.
Read operations require viewer access, while preview and creation require editor access.

Every request is scoped to the project in the URL.
List and detail responses expose only `hogql_event_removal` requests for that project.

## Endpoints

The API is nested under `/api/projects/:team_id/data_deletion_requests/`.

- `POST preview/` validates the query and returns `{ "count": number }`.
- `POST /` creates a deletion request or returns the matching request for an idempotent retry.
- `GET /` lists self-service deletion requests for the project.
- `GET /:id/` returns one self-service deletion request for the project.

Preview accepts `query` and an optional `variables` JSON object.
Creation accepts those fields plus a required client-generated UUID in `submission_id`.
The server rejects undeclared fields, including operational fields such as `status`, `request_type`, `team_id`, and `execution_mode`.
It assigns the project, actor, request type, approval state, and execution mode.

The HogQL query must return exactly one UUID column.
It runs with the submitting user's HogQL access controls.
The API limits the query and serialized variables to 100,000 bytes each.

## Limits and idempotency

Preview uses one project-wide budget for all session and API-key callers.
It permits five requests per minute and 30 requests per hour.
Creation permits 10 requests per hour for the project.

A project can have at most five active self-service requests across `pending`, `approved`, `in_progress`, and `queued` states.
The API enforces this limit under a project-scoped PostgreSQL advisory lock.

The pair of project ID and `submission_id` is unique.
An exact retry returns the existing request without recompiling the query.
Reusing the submission ID with different input or a different actor returns a validation error.

## Approval and status

The first release creates requests in `pending` status with manual approval required.
The API always selects deferred execution, so submission never mutates event storage directly.

After approval, Dagster compiles the stored query with the original actor's access controls and queues UUIDs in ClickHouse.
The existing weekend deletion job removes queued events.
The existing verifier moves the request to `completed` after it confirms that no queued events remain.

The API can return `draft`, `pending`, `approved`, `in_progress`, `queued`, `completed`, or `failed` because those values form the shared deletion workflow contract.
