# PostHog ClickHouse setup quirks

## ClickHouse cluster architecture

Production environment setup.

| cluster   | node role                                        | sharded?                            | comment/purpose                                                                                                                                                                                              |
| --------- | ------------------------------------------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| posthog   | DATA (both `offline` and `online` replica types) | yes,<br>dev: 2,<br>eu: 8,<br>us: 10 | the biggest, main data repository,<br>handles most queries, has distributed tables pointing to satellite nodes' tables,<br>has offline / online replica designation,                                         |
| aux       | AUX (auxiliary)                                  | no                                  | satellite node,<br>all tables that do not have lot data and do not need to be fully replicated on DATA nodes                                                                                                 |
| ai_events | AI_EVENTS                                        | no                                  | satellite node,<br>AI related events and stuff                                                                                                                                                               |
| sessions  | SESSIONS                                         | no                                  | satellite node,<br>sessions related tables, as sessions are all the time updated, this generates huge number of parts that ClickHouse have to merge all the time                                             |
| ops       | OPS                                              | no                                  | satellite node,<br>operation cluster, we keep query_log_archive, metrics, and other operational stuff<br>other nodes exports some metrics here<br>it's suppose to stay up even if the main cluster struggles |
| logs      | LOGS                                             | yes                                 | cluster supporting logs and metrics product (APM)<br>technically a satellite cluster                                                                                                                         |
| events    | INGESTION_EVENTS                                 | no                                  | ingestion layer;<br>used only to consume main events kafka/warpstream topic and ingest events into writable_events                                                                                           |
| medium    | INGESTION_MEDIUM                                 | no                                  | ingestion layer;<br>consumes medium load topics and inserts into clickhouse tables                                                                                                                           |
| small     | INGESTION_SMALL                                  | no                                  | ingestion layer;<br>same as other ingestion, used for the smallest ingestion topics                                                                                                                          |
| endpoints | ENDPOINTS                                        | no                                  | a stateless cluster, mostly runs queries against S3 files                                                                                                                                                    |

All nodes shall have metrics and query_log_archive_mv dumping query_log into ops.query_log_archive.
Ingestion layer should have mostly distributed tables and materialized views.
,

## 4.5 distinct environments

There are local and cloud environments.

### Local

The local one is started directly from the `PostHog/posthog` repository.
Development happens on a 1 node ClickHouse that has all (logical) clusters.
There is a test setup that spins multiple clickhouse nodes, each being a separate cluster (DATA + sattelites clusters). It serves only to validate the migrations.

Local deployment uses Kafka.

### Cloud

There are 3 separate cloud deployments:

- dev - think about it as a staging, it's similar to prod, we aim to make it same arch / setup as our main environments
- prod-us - our main and biggest production environment,
- prod-eu - our second environment, for customers who prefer their data to stay in EU,

We use WarpStream in production environment, therefore the MV are different in local and cloud. This leads to the Kafka tables having slightly different schema.

Our cloud environment has some customizations per env, this is mostly the `events` distributed table and `sharded_events` replicated table, that has different materialized columns (`mat_` prefix).

Because of the historical reasons, the nodes may have little differences between tables. This is not on purpose, but a schema drift that needs to be handled long term.

Schema sources of truth:
PostHog/clickhouse-schema repo contains per environment node schema dumps as HCL.

## Migration desired state

We want to achieve a state of full schema of each env and cluster to be represented as HCL.

End state: we have 5 environments schemas as HCL, a golden per cluster, something like:

- local-single (in PostHog/posthog)
  - all.hcl (one node hosts every role, so one golden)
- local-multi (in PostHog/posthog):
  - ops.hcl
  - posthog.hcl
  - auxiliary.hcl
  - ...
- dev (in posthog-cloud-infra):
  - posthog.hcl
  - auxiliary.hcl
  - sessions.hcl
  - ...
- prod-us (in posthog-cloud-infra):
  - posthog.hcl
  - auxiliary.hcl
  - sessions.hcl
  - ai_events.hcl
  - ops.hcl
  - ...
- prod-eu (in posthog-cloud-infra)
  - ...

The above files should be a result of cluster config composed of multiple smaller files.

Repo split (hard rule): cloud env customizations are NEVER committed to PostHog/posthog (it's public; e.g. `mat_` columns encode customer property names).
PostHog/posthog holds only the env-uniform base layers (shared / cloud-uniform / local) and the local goldens; everything env-specific for dev, prod-us, prod-eu (per-env override layers, cloud goldens, the drift catalog) lives in posthog-cloud-infra, composed as pinned vendored base + overrides.

Schema drift. We may ignore minor drifts, we shall collect all of them for the purpose of fixing it.

Envs:

- local single (single node)
- local multi (multi node)
- dev
- prod-us
- prod-eu

Each table shall be **defined** once, if there's a difference between envs, it shall be extended (prefered) or overriden, whatever is simple.

"Defined once" counts _definition_ sites — plain declarations and `abstract` declarations (a copied abstract schema is still a copy). What does **not** count: declarations carrying `extend` (refinements of a definition that lives elsewhere, chschema #173), `patch_*` blocks, and a redeclaration carrying `override = true` (sanctioned whole-replacement — it still copies content, so it stays the last resort). What the rule forbids is the same schema authored in two places, i.e. copied.

`hclexp locate -duplicates` draws exactly this line (verified against the pin: table+`patch_table` → 0, table+`override=true` → 0, `extend` refinements → 0, table+plain redeclaration → 1, abstract+abstract → 1), so it is the enforcement mechanism, not a heuristic. Both repos gate on it against a `duplicates-baseline.txt` that may only shrink.

The patch vocabulary covers tables and materialized views fully, so "express it as a patch" is always available for a content difference. `patch_table` carries `column` and `index` (both with positional `after`), `modify_column` (full replacement column spec — `type` is required), additive `projection`, `engine`, `order_by`, `partition_by`, `ttl` and `settings`; `patch_view` and `patch_dictionary` do the same for views and dictionaries, and `patch_materialized_view` carries `query` (replace) plus the column operations — an MV whose query differs per env stays declared once with per-env query patches. `settings` merge into the target with the patch winning on collision; everything else replaces. Built on demand in PostHog/chschema — #153 (settings merge), #156 (full vocab + `patch_view`/`patch_dictionary`), #159 (positioned column adds), #161 (positioned index adds), #170 (`patch_materialized_view`, MV `override = true`, projections in `patch_table`), #174/#175 (patches resolve with inheritance: a concrete-target patch applies after `extend`, so it can modify, drop, or position against inherited columns; abstract-target patches propagate to every child).

`patch_column` (#165) is the `extend` side of the same idea: a child using `extend` can specialize a single _inherited_ column — type, nullability, default kind, CODEC, TTL, comment — while keeping every unspecified field and the inherited column order. A plain `column` block on a child still means _add_, and still collides with an inherited name. This is what lets one codec-free abstract back both a storage table and its Distributed proxy, with only the storage child declaring CODECs:

```hcl
table "sharded_events" {
  extend = "_event_base"

  patch_column "timestamp" {
    codec = "Delta(8), ZSTD(1)"
  }
}
```

Before that, the choice was to hang the CODECs on the abstract — forcing them onto the proxy too — or to stop sharing and repeat the column list.

In this repo the cross-_role_ duplicates have been factored into `roles/coshared/<member-set>/` layers (one layer per set of stacks that co-host the objects), with env deltas as `patch_*` blocks in the env layers. The events family itself is the `_event_base` pattern live: `roles/shared/event_base.hcl` declares the abstract core once, `sharded_events` and the `events` proxy extend it in `roles/data/shared/`, the sessions nodes' replica of that proxy extends it in `roles/sessions/shared/`, `roles/data/local` carries the local delta as `patch_table` blocks, and posthog-cloud-infra's `overrides/data/<env>/` carry the cloud deltas the same way. The abstract sits in `roles/shared/` because that is the only layer every role composes, and an abstract emits nothing on a node that does not extend it.

Positioning is the one thing a refinement cannot do: `after` is rejected on a column declared inside a table block, where declaration order is the order. A child that must interleave its own columns with inherited ones declares the table, then adds them in a `patch_table` with `after`. `roles/sessions/shared` does exactly that, which is why the sessions events proxy reproduces the live physical column order.

What keeps the baseline non-empty is `raw_sessions_v3` and `channel_definition`, where one name covers a different object per cluster (storage on one, a Distributed proxy on the other). They resolve when the sessions cloud env layers move to posthog-cloud-infra rather than by any restructure here.

The purpose of the extension is to making the schema changes uniform across all envs: think adding a column or table shall be possible in one place and affect all envs.

If a given role is missing in the environment, we probably shall use the main cluster.

The process of migrating to the HCL:

1. collect all dumps from the nodes:
1. dump a single local node from the basic dev setup in posthog/posthog
1. dump each node for multinode setup
1. prepare posthog-clickhouse repo with per-env/per-node dump hcl files
1. for each object in production environment:
1. compare it with all other envs, corresponding clusters (e.g. take ops from all envs)
1. if it's the same every whery -> dump it into shared (PostHog/posthog)
1. if there's a difference, take the shared part (e.g. column list) and put it in shared, then extend it per env — the per-env extension goes straight into posthog-cloud-infra overrides, never into PostHog/posthog
1. it may be that a table HCL is defined as a part of other cluster (e.g. query_log_archive, the base may be defined in other cluster)

The posthog-cloud-infra compose harness (vendored base pinned by sha + overrides) is stood up BEFORE the decomposition starts, so env customizations land there from day one — there is no "move it later" step.

The restructure in PostHog/posthog is in place and there is only ever ONE composition in the repo — no `roles_old/`, no second manifest (a parked parallel copy creates unnecessary chaos).
The legacy state is pinned by a committed `legacy-ref.txt` sha; `bin/snapshot-legacy.sh` copies it into a gitignored `.legacy/` dir locally, so it's easy to introspect just in case, without committing it.
Restructure PRs prove they change nothing by leaving the committed goldens byte-identical.

Full implementation plan: `docs/plans/2026-07-14-hcl-recreate.md`.

## Deployment

1. local and schema changes to base are done in PostHog/posthog, this is also what all tests run against
2. a PR in PostHog/posthog triggers a compose check in posthog-cloud-infra validating the changes still compose under the prod overrides — the `cloud-compose-gate` job in `ci-clickhouse-hcl-schema.yml` dispatches cloud-infra's `ci-clickhouse-hcl-compose-gate.yaml` against the PR head; it asserts composability, not cloud goldens
3. the cloud schema is composed as base + customizations in posthog-cloud-infra
4. when a PR is merged in PostHog/posthog, a base-ref bump PR in posthog-cloud-infra advances the pinned base sha, regenerates the cloud goldens, and generates the full ordered list of SQL queries that will be executed as part of migration (creation of that PR is to be automated)
5. after approval, the PR is merged and a migrator executes a migration

The change recipes (add a table, column, index; env variants) live in [README.md](README.md), "Making a change".

## Repos

- this repo, PostHog/posthog - base repository
- PostHog/clickhouse-schema - schema dumps, github: PostHog/clickhouse-schema
- PostHog/chschema - hclexp, github repo is PostHog/chschema
  - all needed tooling is on main (per-object comparison #139, locate + -duplicates #145); pin >= sha-5756e98
- PostHog/posthog-cloud-infra - a repository with ansible and machine configurations
  - `clickhouse/hcl/` holds the compose harness (vendored base pinned by sha + `overrides/` + data goldens with mat\_ columns) and the compose-gate workflow
- PostHog/charts - kubernetes config and apps deployment scripts, an old / current clickhouse migration mechanism is run here as job in django web app deployemnt
