# `allowed_tools` and MCP delivery

A stored skill carries an `allowed_tools` list.
`render_frontmatter` in `products/skills/backend/marketplace/packaging.py` writes it into `SKILL.md` as the Agent Skills spec's `allowed-tools` string.

The list means different things on different delivery paths.
A harness that reads a skill from a file treats the list as pre-approved tools.
The Agent Skills spec marks `allowed-tools` experimental and says support may vary between agent implementations, so a file harness without support for the field ignores it.
A host that loads a skill over MCP must ignore the list until the user approves that grant.
So `allowed_tools` is a request for access, not a grant of it.

## The delivery paths

| Path                                                | Skill reaches the harness as     | `allowed_tools` effect                      |
| --------------------------------------------------- | -------------------------------- | ------------------------------------------- |
| Zip export (`…/export`)                             | A file on disk                   | Pre-approved, as the Agent Skills spec says |
| Git marketplace (`…/marketplace.git`)               | A file on disk after `git clone` | Pre-approved                                |
| Skill bundle, `content=full` (`…/bundle`)           | A file on disk                   | Pre-approved                                |
| Skill bundle, `content=stub`, and sandbox run state | A pointer file, then MCP         | Ignored until the user approves the grant   |
| MCP `skill-get` (any caller)                        | An MCP response                  | Ignored until the user approves the grant   |

Watch the stub path.
`render_skill_stub_md` writes only the name, the description, and `metadata`, so the pointer file never carries `allowed-tools`.
The agent then fetches the real skill with `skill-get`, which makes the skill MCP-origin content.

## Why the MCP path ignores the list

[SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension), the MCP Skills extension, binds skills to the MCP transport.
Under "No implicit permission grants", a host must not honor frontmatter that widens the model's tool or filesystem reach when the skill arrives over MCP.
The spec names `allowed-tools` directly: a host must ignore it for an MCP-origin skill unless the user approved that grant for that skill.
A remote server that sets the field asks for access on the host.
It does not describe its own environment.

Two further rules matter for us:

- Approval is per skill. Approval of one skill never covers a skill nested in its file space.
- Approval is content-bound. A host revokes it when the file set changes, then asks again.

## What this means for us

- Never treat `allowed_tools` as a security boundary for skill delivery.
  It is author intent there, and no code in the skills product enforces it.
- Signals is the one exception, because it enforces the list itself.
  `emit_report` / `edit_report` in `allowed_tools` is a scout's opt-in to the report channel.
  The runner grants the report scope only to an opted-in skill, and `_assert_report_tool_opted_in` in `products/signals/backend/scout_harness/views.py` fail-closes each write against the skill version the run snapshotted.
  Keep both layers: `products/tasks/backend/temporal/client.py` over-grants the report scope on a fallback path, and is safe only because that write gate exists.
- Keep the field. Every delivery path shipping today reads the skill from a file, so the list still does its job there.
- Say so in author-facing copy. A skill author who relies on the list needs to know that the MCP path drops it.

## Where the copy lives

Keep these in step when the wording changes:

- `products/skills/backend/api/skill_serializers.py`: the `allowed_tools` help text on `LLMSkillSerializer` and `LLMSkillPublishSerializer`.
- `products/skills/backend/api/community_skill_serializers.py`: the `allowed_tools` help text on `CommunitySkillSerializer`.
- `products/skills/backend/tools/skills.py`: the `allowed_tools` field descriptions on `CreateSkillArgs` and `UpdateSkillArgs`.
- `products/skills/mcp/tools.yaml`: the `skill-create` and `skill-update` descriptions. Run `hogli build:openapi` after an edit.
- `products/skills/skills/skills-store/SKILL.md`: the store skill that tells an agent how to create a skill.
