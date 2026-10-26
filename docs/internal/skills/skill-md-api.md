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

## Resource manifests

Two read endpoints return what an MCP server needs to answer `skills/get` and `skills/list`:
every file of a skill, with the SHA-256 and byte size of the exact bytes the store serves for it.
A host rejects a skill whose bytes disagree with the listing, so both endpoints read the digests the store stamped on write.
They never load the skill body or any file content.

Viewset: `products/skills/backend/api/skill_view_versions.py` (`manifest`) and `products/skills/backend/api/skills.py` (`manifests`).
Builder: `products/skills/backend/api/skill_manifest.py` (`build_skill_manifests`).

### One skill

```text
GET /api/projects/{team_id}/llm_skills/name/{skill_name}/manifest/?version=N
```

Same `version` handling, `llm_skill:read` scope, object access check and `403`/`404` rules as `skill-md`.
An unservable skill also returns `200`.

### Many skills

```text
GET /api/projects/{team_id}/llm_skills/manifests/?limit=&offset=&owner_id=&category=&exclude_category=
```

- The latest version of each skill, from the same access-filtered queryset and `limit`/`offset` pagination as the list.
- Takes the list filters (`search`, `created_by_id`, `owner_id`, `category`), plus `exclude_category` to leave one category out, for example `scout`.
- Weak `ETag`, `304` on `If-None-Match`, `X-Skills-Version`, private and no-cache headers, and the list throttles, all shared with the list.
- One query for the page of skills and one for all their file rows, whatever the page size.

### Entry shape

```json
{
  "name": "my-skill",
  "version": 3,
  "frontmatter": { "name": "my-skill", "description": "...", "metadata": { "version": "3" } },
  "resources": [
    { "path": "SKILL.md", "sha256": "<hex>", "size": 1234, "content_type": "text/markdown" },
    { "path": "references/guide.md", "sha256": "<hex>", "size": 567, "content_type": "text/markdown" }
  ],
  "file_count": 2,
  "total_size": 1801,
  "servable": true,
  "unservable_reasons": []
}
```

- `SKILL.md` comes first, then the bundled files sorted by `path`. The Codex sidecar `agents/openai.yaml` from zip export is not a resource.
- `frontmatter` equals the `frontmatter` of `skill-md` for the same version.
- `sha256` is bare hex. The MCP server adds the `sha256:` prefix and the `skill://` URI on the wire.
- `servable` is false when `unservable_reasons` holds any of these codes:

| Code             | When                                                                                     |
| ---------------- | ---------------------------------------------------------------------------------------- |
| `too_many_files` | `file_count` is over `MCP_MAX_SKILL_FILES` (512), counting `SKILL.md`.                   |
| `too_large`      | `total_size` is over `MCP_MAX_SKILL_BYTES` (16 MiB).                                     |
| `digest_missing` | A stored digest or size is null, because the row predates the backfill.                  |
| `spec_problems`  | `compute_spec_problems` reports a problem, the same check `spec_problems` shows authors. |

A null digest is not computed on read. The endpoint logs `llma_skill_manifest_digest_missing` with the skill names.
Run `backfill_skill_digests` before an MCP server serves skills from an environment.

### Keep the stored digests in step with the renderer

`skill_md_sha256` and `skill_md_size` are stamped from `render_skill_md` when a version is written.
A change to the renderer, including `frontmatter_document`, changes the served bytes of every existing skill.
Ship it with a run of `backfill_skill_digests --recompute`. Otherwise every manifest stops matching the bytes the store serves, and hosts ask every user to approve every skill again.
