# Skill bundle API

The skill bundle is one zip of the skills a user created or owns in the team skills store.
A consumer unpacks it into a skills directory (`~/.claude/skills`, `~/.agents/skills`) so a harness discovers the skills natively.
It is for consumers outside a task sandbox, such as a local install into a developer's own skills directory.
A task sandbox does not download it: the task worker runs the same stub selection (`select_skill_stubs`) when it builds the run's processing context and writes the result into `TaskRun.state["store_skills"]`, and the sandbox agent renders one pointer `SKILL.md` per entry from that state, so session start makes no extra request.

Viewset: `products/skills/backend/api/skills.py` (`LLMSkillViewSet.bundle`).
Walk and caps: `products/skills/backend/marketplace/adapters.py` (`build_skill_bundle`).
Stub rendering and zip assembly: `products/skills/backend/marketplace/packaging.py`.

## Endpoint

```text
GET /api/projects/{team_id}/llm_skills/bundle/?content=stub|full&limit=N
```

| Param     | Default | Behavior                                                                                                                                       |
| --------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `content` | `stub`  | `stub` writes one `SKILL.md` per skill with its name, description and instructions to fetch the skill over MCP. `full` writes the whole skill. |
| `limit`   | `50`    | Maximum skills in the zip, newest first, at most `100`. Every skill in the zip costs the agent prompt context on each turn, so keep it small.  |

The response is `application/zip` with `Content-Disposition: attachment; filename="skills-bundle.zip"`.
Each skill sits under `<name>/`.
Send `Accept: application/zip` or leave `Accept` unset; both pass content negotiation.
Error responses are JSON either way.

## Authentication and gating

- Session, personal API key and OAuth callers all work. The action requires `llm_skill:read`, which the sandbox OAuth token already carries.
- Gated by the `skills-store-in-sandbox` feature flag, evaluated for the requesting user with the organization and project groups.
  Flag off returns `404`, so a consumer can treat it as "not enabled".
  Flag service unavailable returns `503`, so a consumer can tell an outage from a disabled flag.
- Throttled per user (`30/minute`, `300/hour`), so one caller cannot exhaust the budget for the rest of the project.

## Which skills are in the zip

A skill is a candidate when the user created version 1 of it or is listed as an owner, it is the latest version, it is not archived, and its category is not `scout` (the scout harness loads its own skill).
The candidate set is filtered by the same object-level access control as the list endpoint, so a skill the list would hide from the user stays out of the bundle.

Candidates are walked newest first.
Each one is either included, skipped or dropped:

- **Skipped**: the skill fails the Agent Skills spec check (missing or over-long description), or it carries a legacy name or file path the harness could not unpack safely (a malformed name, a path that is not canonical, a case-insensitive collision, a file where another entry needs a directory). Skipped skills do not count toward the limit or the byte cap.
- **Dropped**: the skill would cross the `limit` or, for `content=full`, the 5 MB uncompressed byte cap. The walk stops at the first such skill; everything after it is dropped unread. The byte cap counts content plus zip entry names and framing.

## Response headers

| Header              | Meaning                                               |
| ------------------- | ----------------------------------------------------- |
| `X-Skills-Included` | Skills in the zip.                                    |
| `X-Skills-Dropped`  | Skills past the limit or the byte cap.                |
| `X-Skills-Skipped`  | Skills left out because they would not unpack safely. |

Headers carry counts only.
Names are logged server-side (`skills_bundle_skipped`, `skills_bundle_dropped_over_cap`).

## What a stub contains

A stub `SKILL.md` has the skill's `name`, `description` and `metadata.version`, plus `metadata.source: posthog-skills-store` so a consumer can tell store stubs from skills installed by other means.
Its body tells the agent to:

1. Call `skill-get` for the skill and note the returned `version`.
2. Page through the body with `body_offset` until `body_next_offset` is null, passing the same `version` each time.
3. Follow the complete body as the skill's instructions.
4. Fetch any referenced bundled file with `skill-file-get` at that `version` and write it into the skill directory before use.

Pinning the version keeps a publish that lands mid-fetch from mixing two versions of the skill.
Skill content only crosses the MCP server when a skill is invoked; the bundle itself carries discovery metadata only.

## The `phs` bridge in task sandboxes

A task sandbox lists only the user's own skills as stubs, so it also gets a fixed `phs` skill that runs any store skill the user can read, such as a teammate's.
`/phs <name> [arguments]` fetches the skill with `skill-get`, pages through the body and pins the version, the same way a stub does.
`/phs` or `/phs list [keyword]` calls `skill-list`, and a name `skill-get` cannot find triggers a `skill-list` search for close matches.
The bridge reads and runs skills only.

The task worker sets `TaskRun.state["store_skills_bridge"]` from the same `skills-store-in-sandbox` evaluation as `store_skills`.
`store_skills` is empty both when the flag is off and when the user owns no skills, so it cannot carry this switch.
The sandbox agent writes the bridge in `syncStoreSkills` (`packages/agent/packages/harness/src/extensions/skills-store/store-skills.ts`), so the Claude, Codex and Pi servers share it:

- It is written even when `store_skills` is empty, because a user with no skills of their own needs it most.
- It carries the store marker and `metadata.role: bridge`. Pruning keeps it while the switch is on and removes it when the switch is off. It is not counted in the prompt's number of the user's skills.
- A null run state leaves the bridge on disk as it is, the same as stubs.
- A team skill named `phs` in `store_skills` replaces it, including on a resumed sandbox. A non-store skill named `phs` is never replaced.
- `skill-get` resolves in the run's project, so the bridge cannot fetch skills from another project.
