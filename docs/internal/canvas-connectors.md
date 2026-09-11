# Canvas connectors

Canvases can read third-party data with the current viewer's connection. Calls require the `canvas-connectors` team feature flag. The flag fails closed.

## Declare tools

Declare each provider and tool in the source project's capabilities:

```json
{
  "posthog": { "insights": [], "inlineQueries": false, "captureEvents": [], "state": ["user"], "actions": [] },
  "network": { "origins": [] },
  "connectors": [{ "provider": "github", "tools": ["list_pull_requests"] }]
}
```

A canvas with connectors cannot declare shared state. This rule applies to the whole project, including calls in different files. The call and state endpoints also reject this combination on existing versions.

## Catalog

`GET /api/projects/{project_id}/canvases/connectors/` lists native tools, argument schemas, connection status, and connection paths. The optional `mcp_hosts` query parameter is a comma-separated list of server hosts.

The `canvas-connectors-retrieve` MCP tool exposes this catalog to authors. The catalog does not call the upstream tools. Sandbox authors receive only static native tool schemas, with `connected: null`. This response does not read personal connections or MCP installations, even when `mcp_hosts` is set. Viewer calls still include connection status. Sandbox credentials cannot execute connector tools.

## Call a tool

`POST /api/projects/{project_id}/canvases/{canvas_id}/connectors/call/` accepts:

```json
{ "provider": "github", "tool": "list_pull_requests", "arguments": { "repository": "example/app", "state": "open" } }
```

Scoped credentials need both `canvas:write` and `user:read`. A canvas-only credential cannot spend a personal integration credential. Sandbox credentials cannot call connectors.

The endpoint checks channel access, the feature flag, and the current version's declared provider and tool. It limits requests per viewer and canvas. The activity log records the provider, tool, and outcome, but not arguments or results.

Responses contain `status`, `result`, `detail`, `truncated`, and `connect_path`. Status values are `ok`, `not_connected`, `needs_reauth`, `blocked`, `tool_missing`, `write_blocked`, and `upstream_error`. Invalid arguments return HTTP 400. Access and capability failures return HTTP 403.

Results are limited to 256 KiB. Large results become a bounded `preview` with `truncated: true`. Provider parsing failures return `upstream_error`, not an unhandled exception.

## Providers

- `github` exposes `list_pull_requests`, `search_pull_requests`, `get_pull_request_snapshot`, `get_pull_request_checks`, `search_issues`, and `get_file_contents`. Use `owner/name` to select a repository without ambiguity. A bare name uses the connection's account. Calls try the viewer's connections, newest first, until one can read the repository. Rate-limit failures stop retries.
- `mcp:<host>` uses the viewer's personal installation, or the team's shared installation if no personal one exists. It never uses a teammate's personal installation. Existing MCP policy, credential checks, and audit rules apply.
- MCP connector tools must declare `readOnlyHint: true` and start with a recognized read verb: `get`, `list`, `search`, `fetch`, `read`, `find`, `query`, `count`, or `describe`. Write verbs, destructive hints, and an explicit `readOnlyHint: false` block the call. Unknown operations are blocked. An upstream `readOnlyHint: true` alone cannot grant access. These checks cannot prove that an arbitrary upstream tool has no side effects; connect only trusted servers.

When a connection is missing or needs authorization, `connect_path` identifies the settings page. The host must validate the provider before navigation and require a user action.

## GitHub pull request reads

Use `search_pull_requests` for an author's PRs. Do not fetch one repository page and then filter it by author. The search applies filters at GitHub before pagination.

```javascript
const page = await ph.connectors.call('github', 'search_pull_requests', {
  repository: 'example/app',
  author: 'me',
  state: 'open',
  page: 1,
  per_page: 25,
})
```

`author: "me"` uses the GitHub user identity stored on the viewer's connection. It does not use the installation account, canvas author, or terminal credentials. A missing identity returns `upstream_error`; reconnect GitHub or supply an explicit login.

Both list and search accept `page`, `per_page` (1–100), `sort` (`created` or `updated`), and `direction` (`asc` or `desc`). Both default to page 1, sorted by creation time descending. List defaults to 100 results; search defaults to 25. Search also accepts `author`, `draft`, and literal `query` text. Search qualifiers in `query` are quoted, not interpreted. `state` is `open`, `closed`, or `all`, and defaults to `open`.

Successful pages return `pull_requests`, `page`, `per_page`, `has_next_page`, and `next_page`. Follow `next_page` with the same filters and page size. A null `next_page` ends the available pages. Search also returns:

- `total_count`: GitHub's reported match count.
- `incomplete_results`: GitHub could not complete the search. Do not label the result as complete.
- `search_limit_reached`: More than 1000 matches exist. Narrow the filters to reach results beyond GitHub's search limit.

These fields do not replace the outer `truncated` flag, which reports response-size truncation. Check `status` and `truncated` before reading a page. The tools return selected metadata rather than PR bodies to keep pages small. List results retain `head_branch` and `base_branch`; search results omit these fields. Both preserve `state: "open"` for drafts and expose `draft` separately.

Declare `get_pull_request_snapshot` to fetch CI, approval, mergeability, and `head_sha` for a returned PR:

```javascript
const status = await ph.connectors.call('github', 'get_pull_request_snapshot', {
  repository: 'example/app',
  pr_number: 7,
})
```

Snapshot state can be `draft` or `merged`. A null `review_decision` is not approval. Associate each snapshot with its `head_sha`. If a status read fails, keep the PR row and show status as unavailable. Do not replace a failed status read with an empty PR list.

`get_pull_request_checks` accepts the same arguments. It reuses the GitHub client helper that reads all check-run and external commit-status pages. An empty `checks` list is a successful read with no checks. A failed helper returns `upstream_error`, not a successful empty list. The existing issue search and text-only file read contracts do not change.

Connector reads use the host cache, which defaults to 60 seconds. A repeated call can return cached data. A canvas must schedule its own polling; a cache lifetime is not a subscription or a promise of an immediate fresh read.

## Host safety

The canvas host asks the viewer before it sends connector calls. Consent is limited to the canvas version, provider, and tool. The prompt explains that the canvas can receive private data and share it through its declared capabilities. A denied call stays blocked until the viewer retries from a user action.

Connector results and consent use authentication-scoped caches. Account, organization, and project changes clear these caches. Results are also separated by canvas version. Never write connector results into shared canvas state.

Keep the feature flag off until the backend and a host with these checks are deployed. Verify connection failures, cancellation, account changes, and the connector activity log before increasing the rollout.
