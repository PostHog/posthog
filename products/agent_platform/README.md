# agent_platform v2 backend

This is the Django-side data layer for the v2 agent platform refactor (see
[docs/native-refactor.md](../../../docs/native-refactor.md)).

## What's here

- `models_v2.py` — new `AgentApplicationV2`, `AgentRevisionV2`, `AgentSessionV2`
  shapes. Replaces `models.py`'s `AgentApplication` + `AgentApplicationRevision`.

## Cutover plan (pre-prod — DB gets dropped)

1. Add `models_v2` to `apps.py`'s migrations target.
2. Generate a migration that drops the v1 tables and creates the v2 tables.
3. Wire `api.py` to read/write the v2 models. (Existing `api.py` becomes
   reference-only and is deleted post-cutover.)
4. Internal endpoints for `agent-ingress-v2` and `agent-runner-v2` consume the
   v2 tables directly.
5. After step 9 of the refactor sequence, drop `models.py`, rename
   `models_v2.py` → `models.py`, drop the `V2` suffixes from class names.

## The shape

```text
AgentApplicationV2
  team_id, slug, name, description, encrypted_env, live_revision_id, archived
  (unique on slug while archived=false)

AgentRevisionV2
  application_id, parent_revision_id, state, bundle_uri, bundle_sha256, spec(JSONB)
  state: draft → ready → live | archived

AgentSessionV2
  application_id, revision_id, team_id, state, external_key, conversation(JSONB), metadata
  (unique on (application, external_key) while state in queued/running/waiting)
```

The `spec` JSONB is the structural truth — model, triggers, tools, mcps,
skills, secrets, limits, entrypoint. See `@posthog/agent-shared-v2`
for the canonical TypeScript shape (`AgentSpec`).
