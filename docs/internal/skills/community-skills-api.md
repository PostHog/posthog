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
- Gated by `CommunitySkillFeatureFlagPermission`, which requires `llm-analytics-community-skills` alone.
  Skills went GA in June 2026 and the `llm-analytics-skills` flag was removed with it, so there is no base-product flag left to check.
  The flag is evaluated with the organization **and** project group so a per-project rollout matches in-app evaluation, and `POSTHOG_FEATURE_FLAGS_FORCE_ENABLED` is honored for self-hosted.
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
- Installs into auto-running namespaces are refused: the `signals-scout-` and `review-hog-` prefixes,
  whose skills PostHog registers and runs on its own (Signals scouts run with privileged scopes,
  ReviewHog skills auto-enable in a team's PR reviews). The whole `review-hog-` prefix is reserved,
  not only ReviewHog's canonical names, because `products.skills` can't import `products.review_hog`
  to read that list — `review_hog` already depends on `skills`, so the import would cycle. Install a
  community skill whose slug starts with either prefix under a different `new_name`.
- ReviewHog provenance keys (`seeded_by`, `canonical_hash`, `source`) are stripped from copied
  metadata so a catalog entry can't make an installed skill get pruned by ReviewHog's sync.
- Entries with an empty body or description are rejected (an empty description would later fail
  export validation).
- The catalog row is locked and its `deleted` flag re-checked before copying, so a skill removed from
  the catalog mid-install can't be installed.

Errors surface as `400` (invalid payload / duplicate name) or `404` (unknown or removed slug).
A duplicate-name conflict only blames the `new_name` field when the caller actually supplied it.

## Publishing to the community

Publishing runs the other way: it renders a team's own `LLMSkill` into the repo's
`skills/<slug>/SKILL.md` layout and opens a pull request for a maintainer to review.

| Method | Path                                              | Purpose                                  |
| ------ | ------------------------------------------------- | ---------------------------------------- |
| `POST` | `llm_skills/name/{skill_name}/publish-community/` | Open a PR adding or updating this skill. |

Lives on `LLMSkillViewSet` (`products/skills/backend/api/skills.py`), not the community viewset,
because the subject is a team-owned skill.
Rendering and the GitHub calls are in `community_publish_services.py`.

- Gated by `CommunityPublishFeatureFlagPermission`, which applies the same
  `llm-analytics-community-skills` check as the browse endpoints to this action alone. Skills is GA,
  so the flag cannot sit on the viewset.
- Session auth only, and throttled at 6/hour and 20/day. The API-shaped `BurstRateThrottle` would not
  fire here at all: it only counts personal-API-key traffic.
- `display_name` is capped at 64 characters to match `CommunitySkill.name`. A longer name would pass
  review and then be dropped by ingest, so the skill would never appear in the catalog.
- Bundled files are text only. `CommunitySkillFile.content` is a `TextField` and the renderer takes
  `str`, so a skill referencing an image or other binary asset cannot round-trip through the catalog.

### Repo writes

The target repo is public, so a failed publish must not leave anything behind:

- The branch is `community-skill/<slug>`, derived from the slug rather than random, so re-publishing
  rewrites that branch and returns the PR already open for it instead of opening a second one.
- Every rendered file lands in a single tree and commit, built before the branch reference exists.
  A failure part way through leaves no branch, and reviewers see one commit rather than one per file.
- If opening the PR fails, the branch is deleted again.
- Content becomes public at the branch write, before the pull request that moderates it. Confirming
  that with the user is a UI concern, and it gates enabling the flag rather than shipping this code.

Errors surface as `400` (invalid payload), `404` (unknown skill), `502` (GitHub refused a step), or
`503` when the instance has no `COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID` configured. The 503 is the
fail-safe that keeps publishing off until the GitHub App is installed.
