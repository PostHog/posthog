## Problem

We're migrating person/group reads from the Postgres read replica to personhog (gRPC).
The existing rollout mechanism is percentage-based (`PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE` / `PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE`), which randomly samples a percentage of all traffic.
This makes it hard to test the migration end-to-end for specific teams before rolling out broadly — we need a way to deterministically send all traffic for specific team IDs through personhog.

Additionally, the default gRPC timeout of 5s is too generous for a read path that falls back to Postgres on failure.

## Changes

- **Team ID-based rollout**: Added `PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS` and `PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS` config fields (comma-separated team IDs). When set, all traffic for those teams routes through gRPC and percentage-based rollout is ignored.
- **Batch query behavior**: For queries that span multiple teams (`fetchPersonsByDistinctIds`, `fetchGroupsByKeys`, `fetchGroupTypesByTeamIds`), the batch only routes to gRPC when **all** team IDs in the batch are in the rollout set. Mixed batches stay on Postgres.
- **`fetchGroupTypesByProjectIds`**: No team ID is available, so this method continues using the percentage-based check only (stays on Postgres when in team-ID-only mode).
- **Timeout default**: Changed personhog gRPC timeout default from 5s to 1s.

Files touched:

- `common/config.ts`, `ingestion/config.ts` — new config fields + timeout default
- `client.ts` — `shouldUseGrpcForTeam`, `shouldUseGrpcForTeams`, `parseRolloutTeamIds` helpers
- `personhog-person-repository.ts`, `personhog-group-repository.ts` — use team-aware routing
- `index.ts` — build functions parse and pass team IDs
- 5 server entry points — pass new config values through

## How did you test this code?

- Added unit tests for `parseRolloutTeamIds`, `shouldUseGrpcForTeam`, `shouldUseGrpcForTeams` in `client.test.ts`
- Added team ID rollout integration tests in `personhog-person-repository.test.ts` covering: team in set routes to gRPC, team not in set routes to Postgres, percentage ignored when team IDs are set, batch routing
- All 121 existing + new tests pass
- I am an agent and have not tested this manually

## 🤖 LLM context

This PR was co-authored with Claude Code. The implementation was guided by the user who specified the rollout semantics (all-match for batch queries, team IDs override percentage).
