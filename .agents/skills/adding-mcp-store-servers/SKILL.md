---
name: adding-mcp-store-servers
description: Add a third-party MCP server (Linear, Notion, GitHub, ...) to the PostHog MCP store catalog. Use when asked to "add X to the MCP store", expand the MCP server marketplace, or fix a broken catalog entry. Covers finding the vendor's remote MCP endpoint, probing it (handshake, OAuth discovery, DCR), authoring the catalog entry in products/mcp_store/backend/catalog.py, verification tiers, and the operator handoff for servers without Dynamic Client Registration.
---

# Adding a server to the MCP store

The MCP store catalog is code: one entry in `products/mcp_store/backend/catalog.py` per server.
On deploy, `sync_mcp_server_templates` upserts entries into `MCPServerTemplate` rows in every environment — there are no data migrations, no icon assets, and no manual admin steps for most servers.
Adding a server is a small PR to that file.

## Read first

- `products/mcp_store/README.md` — the catalog pipeline, sync semantics, and operator runbook
- `products/mcp_store/backend/catalog.py` — existing entries; match their tone and shape
- `products/mcp_store/backend/probe.py` — what the probe verifies and what `passed_activation_gate` means

## Workflow

1. **Find the vendor's remote MCP endpoint.**
   Check the vendor's docs (search "<vendor> MCP server"); most publish a hosted endpoint like `https://mcp.<vendor>.com/mcp`.
   Only hosted (remote) MCP servers belong in the catalog — local/stdio servers do not.
   Cross-check public MCP registries if the docs are unclear.

2. **Probe it.**

   ```sh
   DEBUG=1 python manage.py probe_mcp_server https://mcp.example.com/mcp
   ```

   The JSON verdict tells you everything the entry needs:
   - `speaks_mcp: false` → wrong URL or not an MCP server. Stop and re-research; never add an unverified URL.
   - `auth_flavor: "oauth_dcr"` with `passed_activation_gate: true` → OAuth with Dynamic Client Registration. The entry is `auth_type="oauth"` and will **activate automatically on merge**.
   - `auth_flavor: "oauth_shared"` → OAuth without DCR. The entry is `auth_type="oauth"` but ships **inactive**; an operator must register an OAuth app with the vendor and paste credentials in Django admin (see the operator checklist below — include it in your PR description).
   - `auth_flavor: "api_key_or_unknown"` or `"open"` → `auth_type="api_key"`; activates automatically on merge.

3. **Author the entry** in `catalog.py`, alphabetically by name:
   - `name` — the vendor's own casing ("PagerDuty", not "Pagerduty").
   - `description` — one sentence, sentence case, verb-first, matching the existing entries ("Manage Linear issues, projects, and team workflows."). No marketing copy.
   - `category` — the closest of `business` / `data` / `design` / `dev` / `infra` / `productivity`.
   - `icon_domain` — the vendor's primary brand domain (`linear.app`, not `mcp.linear.app`). Verify logo.dev has it: `GET /api/projects/@current/hog_functions/icons/?query=<vendor>` from a dev session, or check `https://img.logo.dev/<domain>` renders a real logo.
   - `docs_url` — the vendor's MCP docs page when they have one.

4. **Verify end-to-end when you can (Gate B).**
   The probe covers everything up to the OAuth consent screen.
   If you have an account with the vendor, complete one real install in local dev: run the stack, install the server from the store UI, finish the OAuth flow (or paste an API key), and confirm the tool list populates.
   Record the verification tier in the PR description:
   - **Tier 1**: probe passed + real install verified (tools listed).
   - **Tier 2**: probe passed only (no vendor account available).

5. **Run the checks.**

   ```sh
   hogli test products/mcp_store/backend/test/test_catalog_sync.py
   ```

   `test_catalog_entries_are_valid` catches malformed entries (bad category, duplicate URL, unnormalized icon_domain) before they hit production.

6. **Open the PR** — one server per PR, title `feat(mcp-store): add <name> to the MCP server catalog`.
   State the probe verdict and verification tier in the description.
   For `oauth_shared` servers, include the operator checklist so activation isn't forgotten.

## Operator checklist for oauth_shared servers (paste into the PR)

```md
This server does not support Dynamic Client Registration, so it ships inactive. To activate (per environment, US and EU):

- [ ] Register an OAuth app in the vendor's developer console
- [ ] Redirect URI: `https://us.posthog.com/api/mcp_store/oauth_redirect/` (and the EU equivalent)
- [ ] Paste client ID + secret into Django admin → MCP server templates → <name>
- [ ] OAuth metadata was auto-discovered by the sync; run the "Discover metadata" admin action only if it's empty
- [ ] Tick "is active"
```

## What not to do

- Don't add entries with unprobed URLs — a dead catalog entry is user-visible breakage.
- Don't edit `is_active`, `oauth_credentials`, or `oauth_metadata` expectations into the catalog — those are operational state owned by the row, not by code.
- Don't add icon assets or `icon_key` values — icons resolve from `icon_domain` via logo.dev at render time.
- Don't batch unrelated servers into one PR unless explicitly doing a scaffold sweep; per-server PRs keep review and reverts clean.
