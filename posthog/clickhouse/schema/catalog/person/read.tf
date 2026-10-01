# Distributed tables, views and dictionaries that queries read from.

module "persons_batch_export" {
  source = "../../lib/view"

  enabled  = local.read && !contains(local.deployment.exclude, "persons_batch_export")
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

  enabled  = local.read && !contains(local.deployment.exclude, "persons_batch_export_backfill")
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
