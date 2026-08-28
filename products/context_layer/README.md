# Context layer

An org-wide Markdown wiki in a Git repository, hosted by PostHog, mounted into agent sandboxes, and maintained by nightly dreaming agents. Specified in RFC 1233.

## Store

Each organization gets one Git repo of Markdown, serialized as a `git bundle` in PostHog object storage:

- Bundle location: `context_layer/<organization_id>/bundles/<head_sha>.bundle` (`OBJECT_STORAGE_*` settings).
- Head pointer: `ContextLayerConfig.head_sha` in Postgres, updated with a compare-and-swap so a lost race is explicit. The bundle for the new head is uploaded before the CAS, so a failed CAS never leaves a dangling pointer.
- Writer lock: `context_layer:repo:<organization_id>` in Redis (`SET NX PX 60000`, heartbeat renewal every 20s), so a crashed writer frees the org within a minute.
- Writer protocol (every writer, no exceptions): acquire lock, download bundle, clone to tmp, apply commits, lint, upload new bundle, CAS head, release. On CAS failure: re-pull, retry once, then surface the error.

## Who can read it

Anyone in the organization.
The wiki does not model per-project access: a page synthesized from a restricted project is readable by an organization member who cannot open that project, and the sandbox mount follows the same rule.

That is a deliberate first step, not an oversight.
Enablement used to refuse any organization with a restricted project, which locked out the organizations most likely to want this, and gating the wiki properly needs per-page provenance rather than a path rule, because `org/`, `areas/`, and `decisions/` pages synthesize across projects.
[PROVENANCE.md](PROVENANCE.md) designs that.

Until it exists, treat the wiki as organization-wide reference material, and do not enable it for an organization whose project restrictions carry real separation.

## Default structure

Scaffolded at enablement and enforced by the linter (`backend/repo_lint.py`, also copied into the repo as `scripts/lint`):

```text
AGENTS.md            server-owned map of the wiki + usage guardrails
CLAUDE.md            symlink -> AGENTS.md, for Claude-native harnesses
org/                 mission, ICP, personas, teams, business model
areas/<area>.md      one hub page per product area
decisions/<date>-<slug>.md   product decisions: what, why, who, source
projects/<project-id>/overview.md              project identity and context
projects/<project-id>/spaces/<slug>.md         one page per Desktop Space (frontmatter: team_id, channel_id)
scripts/lint         the structure linter (also run server-side at land)
scripts/publish      the server-owned publishing client
```

The root file is AGENTS.md because the layer must work for every model and harness; the CLAUDE.md symlink covers Claude-native tooling.

During enablement, malformed wiki-link brackets in legacy Space context are encoded as readable HTML entities instead of blocking setup. The imported page includes a note asking the dreaming agent to review and repair those links. Later wiki edits still pass through the strict structure linter.

## Dreaming

A nightly Temporal coordinator (`context-layer-dream-coordinator`, 03:00 UTC) dispatches one cloud task per enabled organization using GPT-5.6 Sol with high reasoning. Before dispatch, deterministic reconciliation creates a project-scoped page for every public Space and regenerates the project and Space indexes. The run works unlocked on its own clone all night, on a dated `dream/<YYYY-MM-DD>` branch, and lands it through the commits endpoint as one two-parent merge commit (`dream: <date>`): `git log --merges` lists the dreams, and `git revert -m 1` undoes a whole night. The skills live in `products/context_layer/skills/` and source context from completed tasks and loops, merged PRs, and instrumented events. Each run also rechecks completed tasks from the previous seven days so work that finishes after an earlier review is not lost behind the incremental cursor. Dream branches may change sourced content pages only; the server rejects changes to repository instructions, generated indexes, scripts, or Space paths. A per-org failure streak pauses a lane after repeated dispatch failures (`ContextLayerConfig.dreaming_paused`).
