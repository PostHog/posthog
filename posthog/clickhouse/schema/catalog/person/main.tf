variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

# Reads from person_distinct_id. Those must exist on the node first.

locals {
}

# Column lists that more than one object uses.

locals {
  kafka_person_columns = [
    { name = "id", type = "UUID" },
    { name = "created_at", type = "DateTime64(3)" },
    { name = "team_id", type = "Int64" },
    { name = "properties", type = "String" },
    { name = "is_identified", type = "Int8" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "UInt64" },
    { name = "last_seen_at", type = "Nullable(DateTime64(3))" },
  ]

  person_columns = concat(local.kafka_person_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}

module "person_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person"
  database = var.database
  layout   = "global"
  columns  = local.person_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, id)"
    indexes = [
      { name = "kafka_timestamp_minmax_person", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
    unmanaged_columns = ["^p?mat_"]
    unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"]
  }
  kafka = {
    topic          = "clickhouse_person"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_person_columns
    settings       = {}
  }
  mv_select  = <<-SQL
id,
    created_at,
    team_id,
    properties,
    is_identified,
    is_deleted,
    version,
    last_seen_at,
    _timestamp,
    _offset
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}

# Distributed tables, views and dictionaries that queries read from.

module "persons_batch_export" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "persons_batch_export")
  database = var.database
  name     = "persons_batch_export"
  query    = <<-SQL
    WITH
        new_persons AS
        (
            SELECT
                id,
                max(version) AS version,
                argMax(_timestamp, person.version) AS _timestamp2
            FROM ${var.database}.person
            WHERE (team_id = {team_id:Int64}) AND (id IN (
                SELECT id
                FROM ${var.database}.person
                WHERE (team_id = {team_id:Int64}) AND (_timestamp >= {interval_start:DateTime64}) AND (_timestamp < {interval_end:DateTime64})
            ))
            GROUP BY id
            HAVING (_timestamp2 >= {interval_start:DateTime64}) AND (_timestamp2 < {interval_end:DateTime64})
        ),
        new_distinct_ids AS
        (
            SELECT argMax(person_id, person_distinct_id2.version) AS person_id
            FROM ${var.database}.person_distinct_id2
            WHERE (team_id = {team_id:Int64}) AND (distinct_id IN (
                SELECT distinct_id
                FROM ${var.database}.person_distinct_id2
                WHERE (team_id = {team_id:Int64}) AND (_timestamp >= {interval_start:DateTime64}) AND (_timestamp < {interval_end:DateTime64})
            ))
            GROUP BY distinct_id
            HAVING (argMax(_timestamp, person_distinct_id2.version) >= {interval_start:DateTime64}) AND (argMax(_timestamp, person_distinct_id2.version) < {interval_end:DateTime64})
        ),
        all_new_persons AS
        (
            SELECT
                id,
                version
            FROM new_persons
            UNION ALL
            SELECT
                id,
                max(version)
            FROM ${var.database}.person
            WHERE (team_id = {team_id:Int64}) AND (id IN (new_distinct_ids))
            GROUP BY id
        )
    SELECT
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf(((pd._timestamp >= {interval_start:DateTime64}) AND (pd._timestamp < {interval_end:DateTime64})) AND (NOT ((p._timestamp >= {interval_start:DateTime64}) AND (p._timestamp < {interval_end:DateTime64}))), pd._timestamp, ((p._timestamp >= {interval_start:DateTime64}) AND (p._timestamp < {interval_end:DateTime64})) AND (NOT ((pd._timestamp >= {interval_start:DateTime64}) AND (pd._timestamp < {interval_end:DateTime64}))), p._timestamp, least(p._timestamp, pd._timestamp)) AS _inserted_at
    FROM ${var.database}.person AS p
    INNER JOIN
    (
        SELECT
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id2,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM ${var.database}.person_distinct_id2
        WHERE (team_id = {team_id:Int64}) AND (person_id IN (
            SELECT id
            FROM all_new_persons
        ))
        GROUP BY distinct_id
    ) AS pd ON p.id = pd.person_id2
    WHERE (team_id = {team_id:Int64}) AND ((id, version) IN (all_new_persons))
    ORDER BY _inserted_at ASC
  SQL
  override = try(local.deployment.overrides["persons_batch_export"], {})

  depends_on = [
    module.person_family,
  ]
}

module "persons_batch_export_backfill" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "persons_batch_export_backfill")
  database = var.database
  name     = "persons_batch_export_backfill"
  query    = <<-SQL
    SELECT
        pd.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf((pd._timestamp < {interval_end:DateTime64}) AND (NOT (p._timestamp < {interval_end:DateTime64})), pd._timestamp, (p._timestamp < {interval_end:DateTime64}) AND (NOT (pd._timestamp < {interval_end:DateTime64})), p._timestamp, least(p._timestamp, pd._timestamp)) AS _inserted_at
    FROM
    (
        SELECT
            team_id,
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM ${var.database}.person_distinct_id2
        PREWHERE team_id = {team_id:Int64}
        GROUP BY
            team_id,
            distinct_id
    ) AS pd
    INNER JOIN
    (
        SELECT
            team_id,
            id,
            max(version) AS version,
            argMax(properties, person.version) AS properties,
            argMax(created_at, person.version) AS created_at,
            argMax(_timestamp, person.version) AS _timestamp
        FROM ${var.database}.person
        PREWHERE team_id = {team_id:Int64}
        GROUP BY
            team_id,
            id
    ) AS p ON (p.id = pd.person_id) AND (p.team_id = pd.team_id)
    WHERE (pd.team_id = {team_id:Int64}) AND (p.team_id = {team_id:Int64}) AND ((pd._timestamp < {interval_end:DateTime64}) OR (p._timestamp < {interval_end:DateTime64}))
    ORDER BY _inserted_at ASC
  SQL
  override = try(local.deployment.overrides["persons_batch_export_backfill"], {})

  depends_on = [
    module.person_family,
  ]
}
