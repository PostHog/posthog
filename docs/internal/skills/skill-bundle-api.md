# Skill bundle API

The skill bundle is one zip of the skills a user created or owns in the team skills store.
A consumer unpacks it into a skills directory (`~/.claude/skills`, `~/.agents/skills`) so a harness discovers the skills natively.
The first consumer is the agent server in a task sandbox, which fetches the bundle at session start.

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
| `limit`   | `20`    | Maximum skills in the zip, newest first, at most `100`. Every skill in the zip costs the agent prompt context on each turn, so keep it small.  |

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
