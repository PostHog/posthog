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
  - schema.hcl
- local-multi (in PostHog/posthog):
  - ops.hcl
  - posthog.hcl
  - aux.hcl
  - ...
- dev (in posthog-cloud-infra):
  - posthog.hcl
  - aux.hcl
  - sessions.hcl
  - ...
- prod-us (in posthog-cloud-infra):
  - posthog.hcl
  - aux.hcl
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

Each table shall be defined once, if there's a difference between envs, it shall be extended (prefered) or overriden, whatever is simple.

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
2. PR in PostHog/posthog shall trigger a run of a check in posthog-cloud-infra that validates that changes could be merged with the prod layer
3. the cloud schema is composed as base + customizations in posthog-cloud-infra
4. when a PR is merged in PostHog/posthog it shall trigger a job and create PR in posthog-cloud-infra to bump pinned version of base; it shall generate a full ordered list of SQL queries that will be executed as part of migration
5. after approval, the PR is merged and a migrator executes a migration

## Repos

- this repo, PostHog/posthog - base repository
- PostHog/clickhouse-schema - schema dumps, github: PostHog/clickhouse-schema
- PostHog/chschema - hclexp, github repo is PostHog/chschema
  - all needed tooling is on main (per-object comparison #139, locate + -duplicates #145); pin >= sha-5756e98
- PostHog/posthog-cloud-infra - a repository with ansible and machine configurations
  - notable branch: pawel/chore/clickhouse-hcl-data-goldens — the compose harness (vendored base + overrides + data goldens with mat\_ columns), to be merged first
- PostHog/charts - kubernetes config and apps deployment scripts, an old / current clickhouse migration mechanism is run here as job in django web app deployemnt
