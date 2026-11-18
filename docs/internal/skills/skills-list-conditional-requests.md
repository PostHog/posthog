# Skills list conditional requests

The skills list returns `304 Not Modified` when a client already has the current response data.
Clients can reuse the body and reduce network traffic.
Each request still validates its parameters, applies access rules, queries the list, and serializes the response.

## Endpoint

```text
GET /api/projects/{team_id}/llm_skills/
```

| Response header    | Value                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------- |
| `ETag`             | Weak validator, `W/"<sha256 hex>"`. Send it as `If-None-Match` to revalidate the list. |
| `X-Skills-Version` | Marketplace version, `1.0.<epoch microseconds>`. This is a content change hint.        |
| `Cache-Control`    | `private, no-cache`. Store the body, but revalidate before reuse.                      |
| `Vary`             | `Authorization, Cookie`. Caches must separate credentials.                             |

A matching `If-None-Match` returns `304` with no body.
A stale or absent validator returns the usual `200` response with a current ETag.
Invalid parameters still return an error, including when `If-None-Match` is `*`.
An invalid page still returns `404`.

## ETag

The ETag hashes the serialized response data, the user ID, the query string, and the deployment revision.
Access changes, owner membership changes, profile edits, category changes, and hard deletions change the ETag when they change the response.
The response also reflects any owner redaction required by the caller's credential.
The validator is weak because it identifies equivalent data across formatting and content encoding changes.

This design saves response bytes.
It does not skip the list query or serialization.
A timestamp aggregate cannot identify all changes in a response that includes access rules and user profiles.
No separate owner aggregate or access fingerprint runs for conditional requests.

## Marketplace version

`team_skills_version` in `products/skills/backend/api/skill_services.py` reads `Max(updated_at)` across the team's skill rows, including archived rows.
The version preserves microseconds with integer arithmetic.
The list and marketplace read this version without a time-based cache.
The marketplace still caches the synthesized repository by team and version.

A publish, file edit, or archive updates a skill timestamp.
In-place category writers must update `updated_at` explicitly.
Owner and profile changes do not change this version.
A hard deletion can leave the maximum timestamp unchanged or move it backward.
Clients must use the ETag to validate the list; `X-Skills-Version` is not a complete list validator.
