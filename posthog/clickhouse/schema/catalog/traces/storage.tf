# Tables that hold data, and the materialized views between them.



module "trace_span_to_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_attributes")
  database = var.database
  name     = "trace_span_to_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_attributes2")
  database = var.database
  name     = "trace_span_to_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_resource_attributes")
  database = var.database
  name     = "trace_span_to_resource_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_resource_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_resource_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_resource_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_resource_attributes2")
  database = var.database
  name     = "trace_span_to_resource_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_resource_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_resource_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_span_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_span_attributes")
  database = var.database
  name     = "trace_span_to_span_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            'name' AS attribute_key,
            name AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            name
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_span_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_span_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_span_to_span_attributes2")
  database = var.database
  name     = "trace_span_to_span_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            'name' AS attribute_key,
            name AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            name
    )
  SQL
  override = try(local.deployment.overrides["trace_span_to_span_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}



module "trace_spans_to_kafka_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "trace_spans_to_kafka_metrics_mv")
  database = var.database
  name     = "trace_spans_to_kafka_metrics_mv"
  to_table = "${var.database}.trace_spans_kafka_metrics"
  query    = <<-SQL
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) AS max_offset,
        maxSimpleState(observed_timestamp) AS max_observed_timestamp,
        maxSimpleState(timestamp) AS max_timestamp,
        maxSimpleState(now()) AS max_created_at,
        maxSimpleState(now() - observed_timestamp) AS max_lag
    FROM ${var.database}.trace_spans
    GROUP BY
        _partition,
        _topic
  SQL
  override = try(local.deployment.overrides["trace_spans_to_kafka_metrics_mv"], {})

  depends_on = [
    module.trace_spans_family,
    module.trace_spans_kafka_metrics_family,
  ]
}
