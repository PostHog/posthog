# Community skills API

The community skills marketplace lets a team browse, install, and upvote agent skills shared
through the [`PostHog/community-skills`](https://github.com/PostHog/community-skills) repo.
The catalog is an **instance-global** read-model — it is not team-scoped — synced hourly from the
repo's `registry.json`.
Installing copies a catalog entry into the team as a regular `LLMSkill`.

Viewset: `products/skills/backend/api/community_skills.py` (`CommunitySkillViewSet`).
Route: registered in `products/skills/backend/routes.py` as `community_skills` under
`/api/projects/{team_id}/community_skills/`.

## Authentication and gating

- Web-app session auth only (`scope_object = "INTERNAL"`); the endpoint is **not** exposed for
  personal-API-key scoping, since the catalog is instance-global.
- Gated by `CommunitySkillFeatureFlagPermission`, which requires **both**
  `llm-analytics-community-skills` (the marketplace) and `llm-analytics-skills` (the base skills
  product the installed skill lands in) to be enabled.
  The flag is evaluated with the organization **and** project group so a per-project rollout matches
  in-app evaluation, and `POSTHOG_FEATURE_FLAGS_FORCE_ENABLED` is honored for self-hosted.
- `install` and `vote` additionally require resource-level `editor` access on `llm_skill`, and are
  rate-limited by a burst + sustained throttle.

## Endpoints

| Method | Path                               | Purpose                                               |
| ------ | ---------------------------------- | ----------------------------------------------------- |
| `GET`  | `community_skills/`                | List catalog entries (paginated; body omitted).       |
| `GET`  | `community_skills/{slug}/`         | Retrieve one entry, including body and file manifest. |
| `POST` | `community_skills/{slug}/install/` | Copy the entry into the team as an `LLMSkill`.        |
| `POST` | `community_skills/{slug}/vote/`    | Toggle the requesting user's upvote.                  |

`{slug}` is the repo directory name.
Slugs are validated at sync against the skill-name pattern, so they are always routable by DRF's
default lookup regex (no `.` or `/`).

### List filters (`GET community_skills/`)

| Param        | Behavior                                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------ |
| `search`     | Case-insensitive substring on name and description; also matches a tag exactly (case-insensitive).     |
| `tag`        | Returns only skills carrying this exact tag (case-insensitive; tags are stored lowercased at sync).    |
| `trust_tier` | One of `official`, `verified`, `community`.                                                            |
| `order_by`   | One of name/created_at/published_at/install_count/vote_count (± prefix). Defaults to `-install_count`. |

## Install behavior

`install_community_skill` (`community_skill_services.py`) copies the entry into a new `LLMSkill`
named after `new_name` (defaulting to the slug) and bumps the catalog's `install_count`.
Because catalog content originates outside the app, the install path re-validates it rather than
trusting the sync:

- Bundled file paths and sizes are re-checked with the same guards as normal skill creation.
- Installs into auto-running namespaces are refused: the `signals-scout-` prefix (whose skills the
  Signals coordinator auto-registers and runs with privileged scopes) and ReviewHog's canonical skill
  names (which auto-enable in a team's PR reviews). Custom `review-hog-*` names stay installable —
  they require explicit enablement.
- ReviewHog provenance keys (`seeded_by`, `canonical_hash`, `source`) are stripped from copied
  metadata so a catalog entry can't make an installed skill get pruned by ReviewHog's sync.
- Entries with an empty body or description are rejected (an empty description would later fail
  export validation).
- The catalog row is locked and its `deleted` flag re-checked before copying, so a skill removed from
  the catalog mid-install can't be installed.

Errors surface as `400` (invalid payload / duplicate name) or `404` (unknown or removed slug).
A duplicate-name conflict only blames the `new_name` field when the caller actually supplied it.
