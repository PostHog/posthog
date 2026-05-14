# Deployments MCP branch follow-up checklist

- [ ] Rename confusing deployment project identifiers
  - [ ] Rename any MCP-exposed `project` / `project_id` value that actually refers to a `DeploymentProject` to `deployment_project_id`.
  - [ ] Update generated/types/UI usage accordingly.

- [ ] Fix MCP UI list drill-down
  - [ ] Add `detail_args` for `deployment-list` so `deployments-get` receives both `id` and `deployment_project_id`.
  - [ ] Use the renamed `deployment_project_id` value in the detail args.

- [ ] Disable or implement `deployments-logs`
  - [ ] Either implement the real log query path, or set `deployments-logs.enabled: false` until it works.

- [x] Remove unused `LogEntryMixin` from `DeploymentViewSet`
  - [x] Drop the import.
  - [x] Remove it from the viewset inheritance list.

- [ ] Add feature-flag visibility validation for deployment MCP tools
  - [ ] Test that deployment MCP tools are not presented when the `deployments` feature flag is off.
  - [ ] Test that deployment MCP tools are presented when the `deployments` feature flag is on.
  - [ ] Test fail-closed behavior if feature-flag evaluation fails.

- [ ] Add a deploy API/tool stub
  - [ ] Add or keep a stub deploy API path that the frontend can wire a deploy button to before real deployment execution is available.
  - [ ] Include optional `branch` input.
  - [ ] Expose/configure the stub through MCP as the deploy tool.
  - [ ] Require `deployment:write` scope.
  - [ ] Mark it `readOnly: false`, `destructive: false`, and `idempotent: false`.
  - [ ] Gate it behind the `deployments` feature flag.
  - [ ] Consider attaching the deployment detail UI app to the stubbed/created deployment response once the response shape is settled.

- [ ] Fix deployment list MCP/OpenAPI params
  - [ ] Expose the supported `status` query param.
  - [ ] Expose the supported `author` query param.
  - [ ] Regenerate MCP/OpenAPI artifacts.

- [ ] Remove bogus params from `deployments-events`
  - [ ] Ensure the generated schema does not expose unsupported `search` or `ordering` params.

- [x] Fix `projects-list` response filtering
  - [x] Resolved by reverting the unrelated core `projects-list` tool enablement, so the incorrect response filter is no longer exposed.

- [x] Revert unrelated core MCP `projects-list` enablement
  - [x] Keep `deployment-projects-list`; it belongs in the deployments MCP surface.
  - [x] Revert the `services/mcp/definitions/core.yaml` change that enables the core PostHog projects/teams `projects-list` tool.
  - [x] Remove/regenerate any generated core MCP artifacts and snapshots caused only by that core tool enablement.
