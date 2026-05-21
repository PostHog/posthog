# TODO — post-migration backfills

Things the migration intentionally drops or defers that we have to revisit before the new PostHog AI ships to non-internal users. Add new items at the bottom with date + owner.

---

## Billing context

**Dropped in:** `01_CONTEXT.md` § 2 (the row for `maxBillingContextLogic`).
**Status:** open.
**Owner:** _unassigned_.

### What we lost

Today `maxBillingContextLogic.tsx` resolves the org's subscription level, trial status, billing period, usage/limits, addons, and ships them as `MaxBillingContext` with every streaming request. Today's prompts (`ee/hogai/chat_agent/prompts/base.py`) reference billing-aware behavior — e.g. recommending upgrades, gating advice on plan, knowing when the user is near a quota.

The new spec drops this on the grounds that "system data injection already happens in the MCP" — i.e. billing data should reach the agent via tools, not via a prompt slice. That's the right *direction*, but the MCP tool side does not yet exist.

### What needs to land before flip

At least one of:

1. **A billing MCP tool.** New tool on the `posthog-data` (or new `posthog-billing`) MCP server exposing what `maxBillingContextLogic` resolves today: `get_billing_context(team_id)` returning subscription level, trial status, current period usage, limits, addons. The agent calls it when billing-relevant questions come up.
2. **A `billing` attachment type.** Auto-attached when the user is on a billing-adjacent scene (settings → billing, usage page). Renders in `<posthog_context>` as `Billing: pro plan, 12d into a 30d trial, 78% of monthly events quota used`. Trivial to implement once the wrapper template lands, but loses the "fetch only if relevant" benefit.
3. **Hybrid.** Auto-attach a one-line summary when the user is on a billing scene; expose the full picture as a tool the agent can call from anywhere.

Bias toward (1) — matches the architecture's "tools over prompts" direction and keeps the agent in control of token spend.

### Acceptance criteria

- The current prompt directives in `base.py` that depend on billing knowledge (recommend-upgrade, quota-aware advice) still produce the right behavior in evals. Without a billing source the agent will either fabricate billing assumptions or refuse to engage — both are regressions.
- The new tool / attachment respects team isolation (use `get_team()` in the serializer, never a request-scoped fallback).
- Eval snapshot tests cover: free plan, paid plan, trial, expired trial, over-quota.

### Cross-references

- `01_CONTEXT.md` § 2 (drop)
- `04_PROMPTS.md` (catalog of prompt segments that mention billing — confirm which become tool-driven vs deleted)

---

<!-- Add new TODOs below, in the same format. -->
