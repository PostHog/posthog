# Customer analytics bulk account API

`GET /api/customer_analytics/external/accounts` returns accounts and their active relationship assignments.
Use a project secret API key or a personal API key with `account:read` scope.
Send the key in the `Authorization: Bearer <key>` header.
The endpoint does not accept the public project token or the legacy team secret token.
Invalid personal and project secret keys share an IP rate limit.
Requests over this limit return HTTP 429.

## Personal API keys

Personal keys require the `project_id` query parameter:

```http
GET /api/customer_analytics/external/accounts?project_id=<project_id>
Authorization: Bearer <personal_api_key>
```

The endpoint accepts current `phx_` keys and legacy personal keys without a prefix.
It uses the standard personal-key parser, which also accepts `personal_api_key` in the request body or query string.

The key must permit access to the selected project and organization.
The key owner must have project access and permission to read accounts.
Creating an account or receiving an individual account grant does not override a resource-level denial.
Organization security rules also apply.
The response includes only accounts the key owner can access.
Account access filters apply before pagination.
The endpoint does not use the key owner's currently selected project.
An unknown project ID returns HTTP 404.
An existing project that the key cannot access returns HTTP 403.
Personal-key permission errors use the standard `type`, `code`, `detail`, and `attr` fields.
Other authentication and scope errors can use the `error` field.
The API schema describes both formats for HTTP 401 and 403.

## Project secret API keys

Project secret keys (`phs_...`) use the project bound to the key.
The `project_id` parameter is optional for these keys.
If supplied, it must match the key's project.
These service keys retain project-wide account access within their scopes.

## Pagination and assignments

The response contains `results` and `next_cursor`.
Pass a non-null `next_cursor` as the next request's `cursor` parameter.
Keep `project_id` and all filters the same for every page.
The default and maximum page size is 100.

Each account's `relationships` object maps relationship names to arrays of assigned users.
Each assignment contains `user_id`, `email`, and `name`.
Roles without active assignments are omitted.
Use `external_id` to match accounts to external records.

Ignored accounts are excluded by default.
Use `include_ignored=true` to include them or `assigned_only=true` to return accounts with active assignments.
Use `managed_only=true` to return accounts with at least one controlled relationship.
This filter includes ignored accounts and cleared roles, and personal-key access rules still apply.
An account absent from the response can be filtered or inaccessible, so absence alone does not mean its ownership was cleared.
