# Design — `SkillTemplate` + `CustomToolTemplate`

**Status:** draft / open questions. **Owner:** ben. **Tracking:** TODO C5 in `services/agent-shared/TODO.md`.

## Problem

Today every skill / custom-tool lives inside one agent's bundle. There's no way
to share a "research methodology" skill or a "Stripe customer lookup" tool
across multiple agents in a team — copy-pasting between bundles means edits
don't propagate, and the canonical PostHog-authored skills (the eventual
authoring-guide, the `web.fetch` reference impl) drift the same way.

We need a library layer: edit once in a central place, import-by-reference into
many agents.

## Proposed shape

Two new tables, both Django ORM in the **posthog DB** (low-churn authoring
data, same layer as `agent_application` + `agent_revision`):

```sql
agent_skill_template
  id              UUID PK
  team_id         INT FK (nullable for global PostHog-canonical skills)
  slug            TEXT — unique within (team_id, slug); '@posthog/<name>' for canonical
  description     TEXT
  body            TEXT — the markdown that gets injected into the system prompt
  created_by      FK users (nullable for canonical)
  created_at, updated_at

agent_custom_tool_template
  id              UUID PK
  team_id         INT FK (nullable for canonical)
  slug            TEXT — unique within (team_id, slug)
  description     TEXT
  args_schema     JSONB — TypeBox / JSON Schema shape
  source          TEXT — TypeScript source
  compiled_js     TEXT — bundler output
  requires_secrets TEXT[] — names of secrets the tool reads via ctx.secrets.ref
  created_by      FK users (nullable for canonical)
  created_at, updated_at
```

Agents reference templates by id from their `spec`:

```jsonc
{
  "skills": [
    { "from_template": "<uuid>", "alias": "research" }, // pulled in at bundle-build time
  ],
  "tools": [{ "kind": "custom_template", "from_template": "<uuid>", "alias": "stripe_customer_lookup" }],
}
```

At `freeze` time the Django side resolves each template ref, copies the body /
source into the revision's bundle (under `skills/<alias>.md` /
`tools/<alias>/*`), and stamps the template version (sha256 of body+source)
into the spec entry. After freeze the revision is wholly self-contained — the
runner never touches templates, only the bundle.

## Open questions

1. **Namespacing**: do we let teams use `@posthog/research` as their own slug
   if no canonical template by that name exists? Probably no — reserve the
   `@posthog/` prefix for PostHog-owned templates only.
2. **Versioning**: when a template body changes, do already-frozen revisions
   that pulled the old version get any signal? Today they keep the old copy
   in their bundle (correct — frozen is immutable). The MCP could surface
   "this template has a new version" on the authoring side as an opt-in
   rebase.
3. **Canonical authoring**: how do PostHog-owned templates get authored? Two
   options — (a) repo-vendored seed files + a management command that
   upserts on deploy, (b) a separate posthog-team API path that lets us
   author them via the same Django endpoints. (a) is simpler; (b) is more
   self-service. Lean toward (a).
4. **Sharing across orgs**: out of scope for v1. Keep templates team-scoped.
5. **Custom-tool secrets discovery**: should `requires_secrets` be declared
   explicitly or extracted from the source? Explicit is more honest;
   compile-time AST extraction has been a footgun in v1.

## Migration notes

- No data migration needed for v0 (no templates exist yet).
- The seed of PostHog-canonical skills lives at `products/agent_stack/backend/canonical_skills/` as
  plain markdown files; a management command (`seed_canonical_templates`)
  reads them on deploy.

## What this unblocks

- `agent_skill_templates_list` + `_create` MCP tools — the "share a skill"
  authoring flow.
- A "library" tab in the wizard scene (frontend C4).
- The Slack @agent-builder bot (C3) can suggest existing templates instead of
  re-deriving the same skill body from scratch each time.

## Out of scope

- Template approval / review workflow.
- Template usage analytics.
- Pre-compiling tools server-side. v1 keeps the existing client-side compile
  step.
