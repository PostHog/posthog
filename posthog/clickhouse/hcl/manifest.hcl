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
# Both managed roles (OPS, LOGS) are modeled for all three cloud envs (dev, prod-us,
# prod-eu); OPS additionally has `local`. OPS carries the env differences; LOGS carries
# the shared managed subset (env-identical, but verified per env for fidelity).
#
# SCOPE: the pilot is OPS + LOGS. The other roles (data/endpoints/aux/ai_events/sessions)
# also host the shared query_log_archive path + custom_metrics, but are intentionally
# left out for now, so node_roles for shared objects derives to [OPS, LOGS] rather than
# every role. To bring a role under management, add its env block and regenerate the
# golden from a host of that role (codegen/README has the extraction).

role "ops" {
  env "local"   { layers = ["roles/shared", "roles/ops/shared", "roles/ops/local"] }
  env "dev"     { layers = ["roles/shared", "roles/ops/shared", "roles/ops/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-eu"] }
}

# The local LOGS node runs a partial/newer schema than the cloud logs nodes, so it
# composes a self-contained roles/logs/local (extracted from the live node) rather
# than the shared cloud layers.
role "logs" {
  env "local"   { layers = ["roles/logs/local"] }
  env "dev"     { layers = ["roles/shared", "roles/logs/shared", "roles/logs/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/logs/shared", "roles/logs/prod", "roles/logs/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/logs/shared", "roles/logs/prod", "roles/logs/prod-eu"] }
}

# AI_EVENTS satellite (LLM analytics). local/hobby run the MSK variant
# (kafka_ai_events_json + ai_events_json_mv) with a sharded_ai_events data table
# + distributed ai_events reader; US/EU run the WarpStream variant
# (kafka_ai_events_json_ws + ai_events_json_ws_mv, MSK dropped by migration 0248)
# writing into a single ai_events data table. roles/ai_events/shared holds the
# env-uniform person / person_distinct_id2 Distributed shims (0240). dev currently
# has only the top-level shared objects (per the latest dump).
role "ai_events" {
  env "local"   { layers = ["roles/shared", "roles/ai_events/shared", "roles/ai_events/local"] }
  env "dev"     { layers = ["roles/shared"] }
  env "prod-us" { layers = ["roles/shared", "roles/ai_events/shared", "roles/ai_events/prod"] }
  env "prod-eu" { layers = ["roles/shared", "roles/ai_events/shared", "roles/ai_events/prod"] }
}

# AUX satellite: auxiliary tables (error tracking, hog invocations, message assets,
# property values, web/marketing preaggregated). roles/auxiliary/shared holds the env-uniform
# objects; local carries the MSK ingest variant (kafka_error_tracking + its MV, MSK
# kafka_hog_invocation_results); prod carries the WarpStream variant. prod-us adds the
# ingestion_warnings tables. prod goldens are dump-baselined (not live-verifiable here).
role "aux" {
  env "local"   { layers = ["roles/shared", "roles/auxiliary/shared", "roles/auxiliary/local"] }
  env "prod-us" { layers = ["roles/shared", "roles/auxiliary/shared", "roles/auxiliary/prod", "roles/auxiliary/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/auxiliary/shared", "roles/auxiliary/prod", "roles/auxiliary/prod-eu"] }
}

# SESSIONS satellite: the local node runs only the shared query_log_archive path
# (session tables are prod-only), so it composes roles/shared alone. prod nodes host
# the session tables (sessions, raw_sessions, raw_sessions_v3), the events replica,
# channel_definition + web_pre_aggregated_teams (+ their dictionaries), and person
# join tables. roles/sessions/shared holds the env-uniform objects; prod-us/prod-eu
# carry the env-specific channel_definition / events / raw_sessions_v3 (prod-us also
# has writable_events_recent). prod goldens are dump-baselined (not live-verifiable here).
role "sessions" {
  env "local"   { layers = ["roles/shared"] }
  env "prod-us" { layers = ["roles/shared", "roles/sessions/shared", "roles/sessions/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/sessions/shared", "roles/sessions/prod-eu"] }
}

# SESSIONSV3 satellite: US-only node hosting the v3 session tables (events replica,
# raw_sessions_v3) plus the query_log_archive path. Dump-baselined.
role "sessionsv3" {
  env "prod-us" { layers = ["roles/shared", "roles/sessionsv3/prod-us"] }
}

# BATCH_EXPORTS satellite: hosts the sharded_events_recent data table (the recent-events
# store the export workers read; data/ops reach it via Distributed proxies) plus the
# query_log_archive path. Env-specific — prod-eu carries an extra historical_migration
# column. Dump-baselined (no local batch-exports node).
role "batch_exports" {
  env "prod-us" { layers = ["roles/shared", "roles/batch_exports/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/batch_exports/prod-eu"] }
}

# DATA cluster: the main sharded cluster (events family, persons/groups, sessions,
# preaggregated + analytics tables). Only the local node is modeled here — it runs the
# base schema migrations produce (MSK events_json_mv, ~135 objects, no per-env mat_
# columns). The prod data clusters carry 200-300 env-specific materialized (mat_)
# columns per env that are added out-of-band and churn constantly, so their goldens
# live in PostHog/posthog-cloud-infra (clickhouse/hcl/), not the OSS gate.
role "data" {
  env "local" { layers = ["roles/shared", "roles/data/local"] }
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
