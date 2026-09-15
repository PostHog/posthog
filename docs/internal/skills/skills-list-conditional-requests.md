# Skills list conditional requests

The skills list endpoint answers `304 Not Modified` for a client that already holds the current list.
A client that polls the store on every connect then pays two aggregate queries per poll instead of the filtered list query, the owner lookup and a full serialized body.
The MCP server answering `skills/list` is the case this exists for.

Viewset: `products/skills/backend/api/skills.py` (`LLMSkillViewSet.list`).
Version and fingerprint: `products/skills/backend/api/skill_services.py` (`team_skills_version`, `skills_list_version`).

## Endpoint

```text
GET /api/projects/{team_id}/llm_skills/
```

| Response header    | Value                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------ |
| `ETag`             | Strong validator, `"<sha256 hex>"`. Send it back as `If-None-Match` to revalidate.         |
| `X-Skills-Version` | The team's content version, `1.0.<epoch millis>`. For clients that compare without a 304.  |
| `Cache-Control`    | `private, no-cache`. Store the body, but revalidate on every use.                          |
| `Vary`             | `Authorization, Cookie`. The validator is per user, so a shared cache must not key on URL. |

A request whose `If-None-Match` matches gets `304` with no body, before the list query runs.
A stale or absent `If-None-Match` gets the usual `200` and a fresh `ETag`.

## What moves the validators

`X-Skills-Version` is `Max(updated_at)` over **all** of the team's skill rows, archived ones included.
A publish adds a row, a file edit publishes a new version, and an archive bumps `updated_at` on the rows it soft-deletes, so the version advances on every change and never regresses.
It is the same version the git marketplace stamps on its plugin, so the two surfaces report one number.

The `ETag` covers more, because the list body shows more than the skill rows:

| Input                  | Why it is in the ETag                                                                           |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| The skills version     | Publishes, file edits and archives.                                                             |
| The team's owner rows  | Owners are keyed on the skill name, so an owner-only `PATCH` changes no skill row.              |
| The requesting user    | Access filtering is per user, so one caller's validator must never match another caller's list. |
| The whole query string | `search`, `created_by_id`, `owner_id`, `category`, ordering and the page all change the body.   |

The version is read uncached.
`team_skills_version_cached` exists for the marketplace, which polls it far more often than it changes; its TTL would let a publish inside the window answer `304` for a list that already moved.

**Known bound.** A change to one member's access, made with no skill and no owner touched, moves neither validator.
That member can revalidate onto their previous list until the next store change.
Nothing new is disclosed, because the client only keeps a body it already received and every read path still enforces access on the skill itself.
