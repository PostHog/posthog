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

The `canvas-connectors-retrieve` MCP tool exposes this catalog to authors. The catalog does not call the upstream tools.

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

- `github` exposes `list_pull_requests`, `search_issues`, and `get_file_contents`. Use `owner/name` to select a repository without ambiguity. A bare name uses the connection's account. Calls try the viewer's connections, newest first, until one can read the repository. Rate-limit failures stop retries.
- `mcp:<host>` uses the viewer's personal installation, or the team's shared installation if no personal one exists. It never uses a teammate's personal installation. Existing MCP policy, credential checks, and audit rules apply.
- MCP connector tools must declare `readOnlyHint: true` and start with a recognized read verb: `get`, `list`, `search`, `fetch`, `read`, `find`, `query`, `count`, or `describe`. Write verbs, destructive hints, and an explicit `readOnlyHint: false` block the call. Unknown operations are blocked. An upstream `readOnlyHint: true` alone cannot grant access. These checks cannot prove that an arbitrary upstream tool has no side effects; connect only trusted servers.

When a connection is missing or needs authorization, `connect_path` identifies the settings page. The host must validate the provider before navigation and require a user action.

## Host safety

The canvas host asks the viewer before it sends connector calls. Consent is limited to the canvas version, provider, and tool. The prompt explains that the canvas can receive private data and share it through its declared capabilities. A denied call stays blocked until the viewer retries from a user action.

Connector results and consent use authentication-scoped caches. Account, organization, and project changes clear these caches. Results are also separated by canvas version. Never write connector results into shared canvas state.

Keep the feature flag off until the backend and a host with these checks are deployed. Verify connection failures, cancellation, account changes, and the connector activity log before increasing the rollout.
