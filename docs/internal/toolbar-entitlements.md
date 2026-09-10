# Toolbar plan entitlements

`GET /api/user/toolbar_entitlements/` requires a logged-in session and access to the toolbar for the current project. It returns an `entitlements` map of feature names to booleans, based on the current organization’s available features. `ToolbarEntitlementsSerializer` defines its OpenAPI response schema.

When the `toolbar-paid-heatmaps` rollout flag is enabled, toolbar heatmaps require `toolbar_heatmaps: true`. Loading, failed requests, and missing entitlements do not grant access. The menu shows a loading state while checking access and offers a retry when access cannot be determined. Only an explicit `false` shows the plan upgrade prompt.

Opening the heatmap menu while access is loading does not enable heatmaps. A confirmed entitlement enables the open menu; refreshing or losing that entitlement disables heatmaps. When the rollout flag is disabled, the toolbar retains its existing behavior.

This is a toolbar UI gate. The rollout flag does not add entitlement enforcement to the heatmap data endpoints.
