---
name: adding-billing-mcp-read-tool
description: Add a new read-only MCP tool that proxies to the billing service. Use when adding a tool under `products/billing/mcp/tools.yaml` that surfaces billing data through PostHog's MCP.
---

# Adding a billing MCP read tool

Billing MCP tools are thin proxies: PostHog handles the OAuth/PAT scope gate
(`billing:read`), the billing service handles role-based authorization
(`IsOrgMember` / `IsOrgAdmin` / `IsOrgOwner`). The JWT minted by
`BillingManager.get_auth_headers` carries the caller's `organization_role`, so
the user's organization role flows end-to-end automatically — you do not
re-implement it on this side.

## Where authorization lives

| Layer           | What it checks                         | Where                                                 |
| --------------- | -------------------------------------- | ----------------------------------------------------- |
| PostHog edge    | OAuth/PAT scope (`billing:read`)       | `required_scopes=` on the action                      |
| Billing service | Organization role (Member/Admin/Owner) | `permission_classes=[...]` on the billing-side action |

If you only need `billing:read`, you do not need to add a new scope. If a new
tool needs `billing:write`, add it to the scopes object in `posthog/scopes.py`
(both the `Literal` and the `frontend/src/types.ts` + `scopes.tsx` mirrors),
then run `python3 bin/build-mcp-oauth-scopes.py` (or `hogli build:openapi`) to
regenerate `services/mcp/src/lib/oauth-scopes.generated.ts`.

## The four edits

1. **billing repo** — add the action to `billing/api/mcp/views.py` with the
   right permission class:

   ```python
   @action(detail=False, methods=["GET"], url_path="usage-snapshot",
           permission_classes=[IsOrgMember])
   def usage_snapshot(self, request):
       ...
   ```

   Write tools (mutations) belong on `IsOrgAdmin`; org-only operations belong
   on `IsOrgOwner`. The default — no permission class — is unauthenticated and
   is not acceptable for an MCP tool.

2. **PostHog `BillingManager`** — add a thin proxy method in
   `ee/billing/billing_manager.py`:

   ```python
   def get_mcp_usage_snapshot(self, organization: Organization) -> dict[str, Any]:
       res = requests.get(
           f"{BILLING_SERVICE_URL}/api/mcp/tools/usage-snapshot/",
           headers=self.get_auth_headers(organization),
       )
       handle_billing_service_error(res)
       return res.json()
   ```

   `get_auth_headers` is what stamps the user's `organization_role` into the
   JWT — never bypass it.

3. **PostHog viewset** — add an `@action` on `ee/api/billing_mcp.py`:

   ```python
   @action(detail=False, methods=["GET"], url_path="usage-snapshot",
           required_scopes=["billing:read"])
   def usage_snapshot(self, request, *args, **kwargs):
       return Response(self._get_billing_manager().get_mcp_usage_snapshot(self.organization))
   ```

4. **Tool manifest** — append an entry to
   `products/billing/mcp/tools.yaml`:

   ```yaml
   usage-snapshot:
     operation: environment_billing_mcp_usage_snapshot
     enabled: true
     scopes:
       - billing:read
     annotations:
       readOnly: true
       destructive: false
       idempotent: true
     title: Get usage snapshot
     description: >
       One-line description of what the tool returns and when to use it.
   ```

   The `operation` string is the DRF `basename` + action name with underscores
   — confirm by running `python manage.py spectacular --file /tmp/schema.yml`
   and grepping for the URL path.

## Trust boundary

PostHog can refuse to even forward the request (e.g. wrong scope, no team).
Billing can refuse the request even if PostHog forwarded it (wrong role). Both
checks must pass. If you find yourself wanting to do role checks on the PostHog
side too, stop — that produces drift. Keep PostHog focused on the scope gate
and let billing own the role gate.
