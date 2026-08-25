# Node composition manifest — the source of truth for object placement, and the file
# `hclexp` itself consumes (`validate -manifest`, `plan -manifest`, `load -manifest`).
#
# A node's schema = compose(its layers, in order). Each role block declares, per env,
# the ordered layer dirs (relative to this file) whose composition is that node's
# desired schema.
#
# node_roles for an object is DERIVED, not declared: it is the set of roles whose
# composition includes the layer that defines the object. check.sh, diff.sh, and the
# migration generator all read this file. Cross-role objects (in roles/shared/) appear
# in every role's composition -> node_roles = every role here; OPS-only objects (under
# roles/ops/) appear only in the ops compositions -> node_roles = [OPS].
#
# Layout: roles/shared/ (objects on every role) + roles/<role>/<env-or-shared>/ where
# `shared` = all envs of that role and `prod` = both prod envs (e.g. the OPS metrics
# suite is prod-only but env-identical).
#
# LOGS is modeled for all three cloud envs (dev, prod-us, prod-eu) and carries the shared
# managed subset (env-identical, but verified per env for fidelity). OPS keeps only its
# local-multi block: posthog-cloud-infra authors the ops env layers and goldens now, and
# vendors roles/ops/shared from here. The satellite roles are modeled where a node of that role exists
# to model: every role the multinode stack runs has a `local-multi` env block, and the
# convergence gate (dump-live.sh + check-live.sh) dumps and gates all of them.
#
# SCOPE: to bring a further role or env under management, add its env block and regenerate
# the golden from a host of that role (codegen/README has the extraction).

role "ops" {
  env "local-multi"   { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/ops/shared", "roles/ops/local"] }
}

# Every logs node composes the trace suite; the local node adds a self-contained
# roles/logs/local (extracted from the live node) for the legacy logs32 family it
# still runs, and skips the cloud-only metrics ingest.
role "logs" {
  env "local-multi"   { layers = ["roles/shared/qla.hcl", "roles/logs/base", "roles/logs/traces", "roles/logs/traces_kafka_metrics", "roles/logs/local"] }
  env "dev"     { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/logs/base", "roles/logs/traces", "roles/logs/traces_kafka_metrics", "roles/logs/shared", "roles/logs/cloud", "roles/logs/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/logs/base", "roles/logs/traces", "roles/logs/traces_kafka_metrics", "roles/logs/shared", "roles/logs/cloud", "roles/logs/prod", "roles/logs/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/logs/base", "roles/logs/traces", "roles/logs/traces_kafka_metrics", "roles/logs/shared", "roles/logs/cloud", "roles/logs/prod", "roles/logs/prod-eu"] }
}

# AI_EVENTS satellite (LLM analytics). local/hobby run the MSK variant
# (kafka_ai_events_json + ai_events_json_mv) with a sharded_ai_events data table
# + distributed ai_events reader; US/EU run the WarpStream variant
# (kafka_ai_events_json_ws + ai_events_json_ws_mv, MSK dropped by migration 0248)
# writing into a single ai_events data table. roles/ai_events/shared holds the
# env-uniform person / person_distinct_id2 Distributed shims (0240). dev runs the
# same WarpStream pipeline as the prod envs; roles/ai_events/dev downsizes the
# Kafka consumer for dev volume.
role "ai_events" {
  env "local-multi"   { layers = ["roles/shared", "roles/coshared/ai_events_data", "roles/ai_events/shared", "roles/ai_events/local"] }
  env "dev"     { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/ai_events_data", "roles/ai_events/shared", "roles/ai_events/prod", "roles/ai_events/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/ai_events_data", "roles/ai_events/shared", "roles/ai_events/prod"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/ai_events_data", "roles/ai_events/shared", "roles/ai_events/prod"] }
}

# AUX satellite: auxiliary tables (error tracking, hog invocations, message assets,
# property values, web/marketing preaggregated). roles/auxiliary/shared holds the env-uniform
# objects; local carries the MSK ingest variant (kafka_error_tracking + its MV, MSK
# kafka_hog_invocation_results); prod carries the WarpStream variant. Every cloud env
# hosts the ingestion_warnings store; prod-us adds the Distributed proxy onto the data
# cluster. prod goldens are dump-baselined (not live-verifiable here).
role "aux" {
  env "local-multi"   { layers = ["roles/shared", "roles/coshared/aux_data", "roles/auxiliary/shared", "roles/auxiliary/local"] }
  env "dev"     { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/aux_data", "roles/coshared/ingestion_warnings_store", "roles/auxiliary/shared", "roles/auxiliary/prod", "roles/auxiliary/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/aux_data", "roles/coshared/ingestion_warnings_store", "roles/auxiliary/shared", "roles/auxiliary/prod", "roles/auxiliary/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/aux_data", "roles/coshared/ingestion_warnings_store", "roles/auxiliary/shared", "roles/auxiliary/prod", "roles/auxiliary/prod-eu"] }
}

# SESSIONS satellite: the local node runs only the shared query_log_archive path
# (session tables are prod-only), so it composes roles/shared alone. prod nodes host
# the session tables (sessions, raw_sessions, raw_sessions_v3), the events replica,
# channel_definition + web_pre_aggregated_teams (+ their dictionaries), and person
# join tables. roles/sessions/shared holds the env-uniform objects; prod-us/prod-eu
# carry the env-specific channel_definition / events / raw_sessions_v3 (prod-us also
# has writable_events_recent). prod goldens are dump-baselined (not live-verifiable here).
# dev carries the channel_definition / web_pre_aggregated_teams objects + dictionaries,
# but raw_sessions_v3 intentionally skips prod's tuning settings and the sessions-family
# relocation is still converging — model a dev env block after it settles.
role "sessions" {
  env "local-multi"   { layers = ["roles/shared"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/sessions_data", "roles/coshared/events_recent_write", "roles/sessions/shared", "roles/sessions/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/sessions_data", "roles/sessions/shared", "roles/sessions/prod-eu"] }
}

# BATCH_EXPORTS satellite: hosts the sharded_events_recent data table (the recent-events
# store the export workers read; data/ops reach it via Distributed proxies) plus the
# query_log_archive path. Env-specific — prod-eu carries an extra historical_migration
# column. Dump-baselined (no local batch-exports node).
role "batch_exports" {
  # dev composes the prod-us stack verbatim (verified zero drift via hclexp diff).
  env "dev"     { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/batch_exports_data", "roles/batch_exports/prod-us"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/batch_exports_data", "roles/batch_exports/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/coshared/batch_exports_data", "roles/batch_exports/prod-eu"] }
}

# DATA cluster: the main sharded cluster (events family, persons/groups, sessions,
# preaggregated + analytics tables). Only the local node is modeled here — it runs the
# base schema migrations produce (MSK events_json_mv, ~135 objects, no per-env mat_
# columns). The prod data clusters carry 200-300 env-specific materialized (mat_)
# columns per env that are added out-of-band and churn constantly, so their goldens
# live in PostHog/posthog-cloud-infra (clickhouse/hcl/), not the OSS gate.
role "data" {
  env "local-multi" { layers = ["roles/shared", "roles/coshared/aux_data", "roles/coshared/sessions_data", "roles/coshared/ai_events_data", "roles/coshared/tophog", "roles/coshared/events_recent", "roles/coshared/events_recent_write", "roles/coshared/batch_exports_data", "roles/coshared/ingestion_warnings_store", "roles/coshared/events_json_write", "roles/coshared/log_entries_write", "roles/coshared/session_replay_write", "roles/data/shared", "roles/data/local"] }
}

# INGESTION satellites: the Kafka consumer layer. Each node carries the kafka_* engine
# tables for its topic class, the MV that reads them, and the writable_* Distributed
# proxies that write into the data cluster (migration 0157 moved this off the data node).
# Beyond that they carry only the shared query_log_archive path. Role names are the
# hostClusterRole macros migrations target: events, small, medium.
role "events" {
  env "local-multi" { layers = ["roles/shared/qla.hcl", "roles/coshared/events_json_write", "roles/ingestion_events/local"] }
}

role "small" {
  env "local-multi" { layers = ["roles/shared/qla.hcl", "roles/coshared/log_entries_write", "roles/coshared/session_replay_write", "roles/ingestion_small/local"] }
}

role "medium" {
  env "local-multi" { layers = ["roles/shared/qla.hcl", "roles/ingestion_medium/local"] }
}

# The plain dev/hobby stack (docker-compose.dev.yml): ONE ClickHouse server hosting every
# role's objects, because migration_tools routes every migration to NodeRole.ALL when DEBUG
# and not MULTINODE_CLICKHOUSE. Composed as the deduped union of the local-multi stacks it
# hosts, so any name two of those roles declare fails this load instead of drifting.
role "all" {
  env "local-single" { layers = ["roles/shared", "roles/coshared/custom_metrics", "roles/ops/shared", "roles/ops/local", "roles/logs/base", "roles/logs/traces", "roles/logs/traces_kafka_metrics", "roles/logs/local", "roles/coshared/ai_events_data", "roles/ai_events/shared", "roles/ai_events/local", "roles/coshared/aux_data", "roles/auxiliary/shared", "roles/auxiliary/local", "roles/coshared/sessions_data", "roles/coshared/tophog", "roles/coshared/events_recent", "roles/coshared/events_recent_write", "roles/coshared/batch_exports_data", "roles/coshared/ingestion_warnings_store", "roles/coshared/events_json_write", "roles/coshared/log_entries_write", "roles/coshared/session_replay_write", "roles/data/shared", "roles/data/local", "roles/ingestion_events/local", "roles/ingestion_small/local", "roles/ingestion_medium/local"] }
}

# role "endpoints" {
#   env "prod-us" { layers = ["roles/shared"] }
# }

# ---------------------------------------------------------------------------
# Cluster mapping — cross-cluster Distributed proxies resolve against their
# target cluster's composition (remote existence + column agreement) instead of
# -skip-validation.
#
#   roles    node roles whose compositions union into the cluster's schema
#            (resolved per -env). Each must be a role block above.
#   aliases  optional remote_servers aliases sharing the cluster's schema.
#
# Env-independent: `hclexp validate -env <env>` selects each role's stack, and a
# cluster whose roles aren't composed in that env resolves @absent on its own
# (chschema #127). So the `posthog` data cluster — modeled here only for `local`,
# prod goldens in posthog-cloud-infra — is validated for `local` and absent for the
# cloud envs, from this one declaration, no per-env handling.
#
# `system.*` remotes are always resolvable and need no entry.
# ---------------------------------------------------------------------------

cluster "ops" { roles = ["ops"] }

cluster "logs" { roles = ["logs"] }

cluster "aux" { roles = ["aux"] }

cluster "ai_events" { roles = ["ai_events"] }

cluster "batch_exports" { roles = ["batch_exports"] }

cluster "posthog" {
  roles   = ["data"]
  aliases = ["posthog_writable", "posthog_primary_replica", "posthog_single_shard"]
}
