# `allowed_tools` and MCP delivery

A stored skill carries an `allowed_tools` list.
`render_frontmatter` in `products/skills/backend/marketplace/packaging.py` writes it into `SKILL.md` as the Agent Skills spec's `allowed-tools` string.

The list means different things on different delivery paths.
A harness that reads a skill from a file treats the list as pre-approved tools.
The Agent Skills spec marks `allowed-tools` experimental and says support may vary between agent implementations, so a file harness without support for the field ignores it.
A host that loads a skill over MCP must ignore the list until the user approves that grant.
So `allowed_tools` is a request for access, not a grant of it.

## The delivery paths

| Path                                                | Skill reaches the harness as     | `allowed_tools` effect                                       |
| --------------------------------------------------- | -------------------------------- | ------------------------------------------------------------ |
| Zip export (`…/export`)                             | A file on disk                   | Pre-approved, as the Agent Skills spec says                  |
| Git marketplace (`…/marketplace.git`)               | A file on disk after `git clone` | Pre-approved                                                 |
| Skill bundle, `content=full` (`…/bundle`)           | A file on disk                   | Pre-approved                                                 |
| Skill bundle, `content=stub`, and sandbox run state | A pointer file, then MCP         | No grant. The stub omits the list, then `skill-get` sends it |
| MCP `skill-get`                                     | An MCP response                  | No grant. The list arrives as data                           |
| `learn project:<skill>`                             | An MCP response                  | No grant. The list never reaches the client                  |
| PostHog AI `get_llm_skill`                          | Text in the model's context      | No grant. The list is printed as text                        |

Watch the stub path.
`render_skill_stub_md` writes only the name, the description, and `metadata`, so the pointer file never carries `allowed-tools`.
The agent then fetches the real skill with `skill-get`, which makes the skill MCP-origin content.

`learn project:<skill>` carries less again.
`formatLearnDocument` in `services/mcp/src/skills/skill-catalog.ts` strips the frontmatter and prints the description, the file manifest, and the body, so the list never reaches the client.

The PostHog AI path is different again.
`_format_skill_detail` in `products/skills/backend/tools/skills.py` prints `Allowed tools:` into the text the model reads.
The tool description tells the model to treat the body as instructions, but nothing acts on the tool list.

## Why the MCP path ignores the list

[SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension), the MCP Skills extension, binds skills to the MCP transport.
Under "No implicit permission grants", a host must not honor frontmatter that widens the model's tool or filesystem reach when the skill arrives over MCP.
The spec names `allowed-tools` directly: a host must ignore it for an MCP-origin skill unless the user approved that grant for that skill.
A remote server that sets the field asks for access on the host.
It does not describe its own environment.

Our MCP server does not advertise the extension yet.
`SERVER_CAPABILITIES` in `services/mcp/src/hono/dispatcher.ts` declares `tools`, `resources`, and `prompts`, and the server implements no `skills/list` or `skills/get`.
A host reads a skill as an ordinary tool result, so it cannot bind an approval to it.
The rule still sets the posture we hold: no MCP path grants a tool today, and the list stays a request on all of them.

Two further rules matter once we expose the extension:

- Approval is per skill. Approval of one skill never covers a skill nested in its file space.
- Approval is content-bound. A host binds it to every file URI and digest it saw, so an edit to a file revokes it just as an added or removed file does.
  A body edit is enough, because the set covers the `SKILL.md` digest. The host then asks again.

## What this means for us

- Never treat `allowed_tools` as a security boundary for skill delivery.
  It is author intent there, and no code in the skills product enforces it.
- Signals is the one exception, because it enforces the list itself.
  `emit_report` / `edit_report` in `allowed_tools` is a scout's opt-in to the report channel.
  The runner grants the report scope only to an opted-in skill, and `_assert_report_tool_opted_in` in `products/signals/backend/scout_harness/views.py` fail-closes each write against the skill version the run snapshotted.
  Keep both layers: `products/tasks/backend/temporal/client.py` over-grants the report scope on a fallback path, and is safe only because that write gate exists.
- Keep the field. The file delivery paths still read it, so the list does its job there.
- Say so in author-facing copy. A skill author who relies on the list needs to know that the MCP path drops it.

## Where the copy lives

Keep these in step when the wording changes:

- `products/skills/backend/api/skill_serializers.py`: the `allowed_tools` help text on `LLMSkillSerializer` and `LLMSkillPublishSerializer`.
- `products/skills/backend/api/community_skill_serializers.py`: the `allowed_tools` help text on `CommunitySkillSerializer`.
- `products/skills/backend/tools/skills.py`: the `allowed_tools` field descriptions on `CreateSkillArgs` and `UpdateSkillArgs`.
- `products/skills/mcp/tools.yaml`: the `skill-create` and `skill-update` descriptions. Run `hogli build:openapi` after an edit.
- `products/skills/skills/skills-store/SKILL.md`: the store skill that tells an agent how to create a skill.
- `products/skills/skills/working-with-skills/SKILL.md`: the playbook skill that pairs with `skills-store`.
