# SKILL.md API

One skill's `SKILL.md` as the store renders it, plus the same frontmatter as a JSON object.

It exists for a host that serves a skill as a file — the MCP skills extension serves
`skill://<prefix>/<name>/SKILL.md` and must list the file's frontmatter field for field.
A host that renders the frontmatter itself would drift from the store, and every digest taken over
the file would then disagree with the listing. So both halves of this response come from one
renderer.

Viewset: `products/skills/backend/api/skills.py` (`LLMSkillViewSet.skill_md`).
Rendering: `products/skills/backend/marketplace/packaging.py` (`render_skill_md`, `frontmatter_document`).

## Endpoint

```text
GET /api/projects/{team_id}/llm_skills/name/{skill_name}/skill-md/?version=N
```

| Param     | Default        | Behavior                                                 |
| --------- | -------------- | -------------------------------------------------------- |
| `version` | latest version | Pins the response to one published version of the skill. |

Response:

```json
{
  "name": "my-skill",
  "version": 3,
  "content": "---\nname: my-skill\n...\n---\n\n<body>",
  "frontmatter": { "name": "my-skill", "description": "...", "metadata": { "version": "3" } }
}
```

- `content` is the complete file: the frontmatter block, a blank line, then the body. Take a digest over this exact string.
- `frontmatter` equals `yaml.safe_load` of the block in `content`. Keys use the spec's own names, so tool names arrive under `allowed-tools`.
- The body is not paged. `MAX_SKILL_BODY_BYTES` caps it at 1 MB.

## Authentication and access

- Session, personal API key and OAuth callers all work. The action requires the `llm_skill:read` scope.
- Object-level access control matches the other read actions on this viewset: a skill the caller cannot reach returns `403`, not `404`.
- `404` for an unknown skill name and for a version the skill never published.

## Frontmatter shape

`frontmatter_document` maps storage shape to spec shape:

| Stored          | Served                                                    |
| --------------- | --------------------------------------------------------- |
| `name`          | `name`                                                    |
| `description`   | `description`                                             |
| `license`       | `license`, omitted when empty                             |
| `compatibility` | `compatibility`, omitted when empty                       |
| `metadata`      | `metadata`, with `version` written last so it always wins |
| `allowed_tools` | `allowed-tools`, space separated, omitted when empty      |

The spec has no top-level version field, so the platform version is parked under
`metadata.version`. It is a string, and it changes on every publish even when the body does not,
so the rendered file changes with it.
