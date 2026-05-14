# Deployments MCP branch follow-up checklist

- [x] Rename confusing deployment project identifiers
  - [x] Rename any MCP-exposed `project` / `project_id` value that actually refers to a `DeploymentProject` to `deployment_project_id`.
  - [x] Update generated/types/UI usage accordingly.

- [x] Fix MCP UI list drill-down
  - [x] Add `detail_args` for `deployment-list` so `deployments-get` receives both `id` and `deployment_project_id`.
  - [x] Use the renamed `deployment_project_id` value in the detail args.

- [x] Disable or implement `deployments-logs`
  - [x] Set `deployments-logs.enabled: false` until it works.

- [x] Remove unused `LogEntryMixin` from `DeploymentViewSet`
  - [x] Drop the import.
  - [x] Remove it from the viewset inheritance list.

- [x] Add feature-flag visibility validation for deployment MCP tools
  - [x] Test that deployment MCP tools are not presented when the `deployments` feature flag is off.
  - [x] Test that deployment MCP tools are presented when the `deployments` feature flag is on.
  - [x] Test fail-closed behavior if feature-flag evaluation fails.

- [x] Add a deploy API/tool endpoint
  - [x] Add a deploy API path that the frontend can wire a deploy button to before execution is fully available.
  - [x] Include optional `branch` input.
  - [x] Expose/configure the endpoint through MCP as the deploy tool.
  - [x] Require `deployment:write` scope.
  - [x] Mark it `readOnly: false`, `destructive: false`, and `idempotent: false`.
  - [x] Gate it behind the `deployments` feature flag.
  - [x] Return only the created deployment id.

- [x] Fix deployment list MCP/OpenAPI params
  - [x] Expose the supported `status` query param.
  - [x] Expose the supported `author` query param.
  - [x] Regenerate MCP/OpenAPI artifacts.

- [x] Remove bogus params from `deployments-events`
  - [x] Ensure the generated schema does not expose unsupported `search` or `ordering` params.

- [x] Fix `projects-list` response filtering
  - [x] Resolved by reverting the unrelated core `projects-list` tool enablement, so the incorrect response filter is no longer exposed.

- [x] Revert unrelated core MCP `projects-list` enablement
  - [x] Keep `deployment-projects-list`; it belongs in the deployments MCP surface.
  - [x] Revert the `services/mcp/definitions/core.yaml` change that enables the core PostHog projects/teams `projects-list` tool.
  - [x] Remove/regenerate any generated core MCP artifacts and snapshots caused only by that core tool enablement.
