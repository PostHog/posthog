# Tables that hold data, and the materialized views between them.











module "metrics2_input" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input")
  database = var.database
  name     = "metrics2_input"
  engine   = "`Null`"
  columns  = local.metrics2_input_columns
  override = try(local.deployment.overrides["metrics2_input"], {})
}

module "metrics2_input_to_metric_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metric_attributes")
  database = var.database
  name     = "metrics2_input_to_metric_attributes"
  to_table = "${var.database}.metric_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metric_attributes"], {})

  depends_on = [
    module.metric_attributes2_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metric_attributes3")
  database = var.database
  name     = "metrics2_input_to_metric_attributes3"
  to_table = "${var.database}.metric_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metric_attributes3"], {})

  depends_on = [
    module.metric_attributes3_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_names3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metric_names3")
  database = var.database
  name     = "metrics2_input_to_metric_names3"
  to_table = "${var.database}.metric_names3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toStartOfHour(timestamp) AS time_bucket,
        toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
        maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
    FROM ${var.database}.metrics2_input AS input
    WHERE has_labels
    GROUP BY
        team_id,
        time_bucket,
        metric_name,
        original_expiry_time_bucket
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metric_names3"], {})

  depends_on = [
    module.metric_names3_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_series" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metric_series")
  database = var.database
  name     = "metrics2_input_to_metric_series"
  to_table = "${var.database}.metric_series2"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp AS last_seen,
        original_expiry_timestamp
    FROM ${var.database}.metrics2_input
    WHERE has_labels
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metric_series"], {})

  depends_on = [
    module.metric_series2_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_series3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metric_series3")
  database = var.database
  name     = "metrics2_input_to_metric_series3"
  to_table = "${var.database}.metric_series3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp AS last_seen,
        original_expiry_timestamp
    FROM ${var.database}.metrics2_input
    WHERE has_labels
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metric_series3"], {})

  depends_on = [
    module.metric_series3_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metrics" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_metrics")
  database = var.database
  name     = "metrics2_input_to_metrics"
  to_table = "${var.database}.metrics2"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        resource_fingerprint,
        timestamp,
        observed_timestamp,
        original_expiry_timestamp,
        service_name,
        metric_type,
        value,
        count,
        histogram_bounds,
        histogram_counts,
        trace_id,
        span_id,
        trace_flags,
        has_labels,
        unit,
        aggregation_temporality,
        is_monotonic,
        instrumentation_scope,
        _partition,
        _topic,
        _offset
    FROM ${var.database}.metrics2_input
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_metrics"], {})

  depends_on = [
    module.metrics2_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_resource_attributes")
  database = var.database
  name     = "metrics2_input_to_resource_attributes"
  to_table = "${var.database}.metric_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_resource_attributes"], {})

  depends_on = [
    module.metric_attributes2_family,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_resource_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics2_input_to_resource_attributes3")
  database = var.database
  name     = "metrics2_input_to_resource_attributes3"
  to_table = "${var.database}.metric_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics2_input_to_resource_attributes3"], {})

  depends_on = [
    module.metric_attributes3_family,
    module.metrics2_input,
  ]
}


module "metrics4_input" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input")
  database = var.database
  name     = "metrics4_input"
  engine   = "`Null`"
  columns  = local.metrics2_input_columns
  override = try(local.deployment.overrides["metrics4_input"], {})
}

module "metrics4_input_to_metrics4_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input_to_metrics4_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_attributes_family,
  ]
}

module "metrics4_input_to_metrics4_names" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input_to_metrics4_names")
  database = var.database
  name     = "metrics4_input_to_metrics4_names"
  to_table = "${var.database}.writable_metrics4_names"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toStartOfHour(timestamp) AS time_bucket,
        toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
        maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
    FROM ${var.database}.metrics4_input AS input
    WHERE has_labels
    GROUP BY
        team_id,
        time_bucket,
        metric_name,
        original_expiry_time_bucket
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_names"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_names_family,
  ]
}

module "metrics4_input_to_metrics4_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input_to_metrics4_resource_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_resource_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_resource_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_attributes_family,
  ]
}

module "metrics4_input_to_metrics4_samples" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input_to_metrics4_samples")
  database = var.database
  name     = "metrics4_input_to_metrics4_samples"
  to_table = "${var.database}.writable_metrics4_samples"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toDateTime(toStartOfHour(timestamp)) AS time_bucket,
        series_fingerprint,
        toDate32(original_expiry_timestamp) AS original_expiry_date,
        any(resource_fingerprint) AS resource_fingerprint,
        any(service_name) AS service_name,
        any(metric_type) AS metric_type,
        any(unit) AS unit,
        any(aggregation_temporality) AS aggregation_temporality,
        max(toUInt8(is_monotonic)) AS is_monotonic,
        max(toUInt8(has_labels)) AS has_labels,
        any(instrumentation_scope) AS instrumentation_scope,
        anyLast(histogram_bounds) AS histogram_bounds,
        any(_topic) AS _topic,
        groupArray(10000)(timestamp) AS timestamp_arr,
        groupArray(10000)(observed_timestamp) AS observed_timestamp_arr,
        groupArray(10000)(value) AS value_arr,
        groupArray(10000)(count) AS count_arr,
        groupArray(10000)(histogram_counts) AS histogram_counts_arr,
        groupArray(10000)(trace_id) AS trace_id_arr,
        groupArray(10000)(span_id) AS span_id_arr,
        groupArray(10000)(trace_flags) AS trace_flags_arr
    FROM ${var.database}.metrics4_input
    GROUP BY
        team_id,
        metric_name,
        time_bucket,
        series_fingerprint,
        original_expiry_date
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_samples"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_samples_family,
  ]
}

module "metrics4_input_to_metrics4_series" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "metrics4_input_to_metrics4_series")
  database = var.database
  name     = "metrics4_input_to_metrics4_series"
  to_table = "${var.database}.writable_metrics4_series"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp,
        original_expiry_timestamp
    FROM ${var.database}.metrics4_input
    WHERE has_labels
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_series"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_series_family,
  ]
}
