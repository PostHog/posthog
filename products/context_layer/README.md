# Context layer

An org-wide Markdown wiki in a Git repository, hosted by PostHog, mounted into agent sandboxes, and maintained by nightly dreaming agents. Specified in RFC 1233.

## Store

Each organization gets one Git repo of Markdown, serialized as a `git bundle` in PostHog object storage:

- Bundle location: `context_layer/<organization_id>/bundles/<head_sha>.bundle` (`OBJECT_STORAGE_*` settings).
- Head pointer: `ContextLayerConfig.head_sha` in Postgres, updated with a compare-and-swap so a lost race is explicit. The bundle for the new head is uploaded before the CAS, so a failed CAS never leaves a dangling pointer.
- Writer lock: `context_layer:repo:<organization_id>` in Redis (`SET NX PX 60000`, heartbeat renewal every 20s), so a crashed writer frees the org within a minute.
- Writer protocol (every writer, no exceptions): acquire lock, download bundle, clone to tmp, apply commits, lint, upload new bundle, CAS head, release. On CAS failure: re-pull, retry once, then surface the error.

## Default structure

Scaffolded at enablement and enforced by the linter (`backend/repo_lint.py`, also copied into the repo as `scripts/lint`):

```text
AGENTS.md            map of the wiki + usage guardrails (agent-evolvable)
CLAUDE.md            symlink -> AGENTS.md, for Claude-native harnesses
org/                 mission, ICP, personas, teams, business model
areas/<area>.md      one hub page per product area
decisions/<date>-<slug>.md   product decisions: what, why, who, source
channels/<slug>.md   one page per Desktop channel (frontmatter: channel_id)
scripts/lint         the structure linter (also run server-side at land)
```

The root file is AGENTS.md because the layer must work for every model and harness; the CLAUDE.md symlink covers Claude-native tooling.
