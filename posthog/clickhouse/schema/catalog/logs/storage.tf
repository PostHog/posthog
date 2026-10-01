# Tables that hold data, and the materialized views between them.

module "kafka_logs_avro_billing_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "kafka_logs_avro_billing_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_billing_metrics_mv"
  to_table = "${var.database}.logs_billing_metrics"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
        sumSimpleState(_bytes_compressed) AS bytes_compressed,
        sumSimpleState(1) AS record_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
            service_name AS service_name,
            _bytes_uncompressed,
            _bytes_compressed
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name
  SQL
  override = try(local.deployment.overrides["kafka_logs_avro_billing_metrics_mv"], {})

  depends_on = [
    module.logs34_family,
    module.logs_billing_metrics_family,
  ]
}

module "kafka_logs_avro_kafka_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "kafka_logs_avro_kafka_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_kafka_metrics_mv"
  to_table = "${var.database}.logs_kafka_metrics"
  query    = <<-SQL
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) AS max_offset,
        maxSimpleState(observed_timestamp) AS max_observed_timestamp,
        maxSimpleState(timestamp) AS max_timestamp,
        maxSimpleState(now()) AS max_created_at,
        maxSimpleState(now() - observed_timestamp) AS max_lag
    FROM ${var.database}.logs34
    GROUP BY
        _partition,
        _topic
  SQL
  override = try(local.deployment.overrides["kafka_logs_avro_kafka_metrics_mv"], {})

  depends_on = [
    module.logs34_family,
    module.logs_kafka_metrics_family,
  ]
}





module "logs32_to_log_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "logs32_to_log_attributes")
  database = var.database
  name     = "logs32_to_log_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_log_attributes"], {})

  depends_on = [
    module.log_attributes_family,
    module.logs32_family,
  ]
}

module "logs32_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "logs32_to_resource_attributes")
  database = var.database
  name     = "logs32_to_resource_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            resource_attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_resource_attributes"], {})

  depends_on = [
    module.log_attributes_family,
    module.logs32_family,
  ]
}


module "logs34_to_log_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "logs34_to_log_attributes3")
  database = var.database
  name     = "logs34_to_log_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            attributes
    )
  SQL
  override = try(local.deployment.overrides["logs34_to_log_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs34_family,
  ]
}

module "logs34_to_resource_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "logs34_to_resource_attributes3")
  database = var.database
  name     = "logs34_to_resource_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            resource_attributes
    )
  SQL
  override = try(local.deployment.overrides["logs34_to_resource_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs34_family,
  ]
}

module "logs34_to_volume_buckets" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "logs34_to_volume_buckets")
  database = var.database
  name     = "logs34_to_volume_buckets"
  to_table = "${var.database}.logs_volume_buckets"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text,
        maxSimpleState(retention_days) AS retention_days,
        sumSimpleState(1) AS log_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
            service_name,
            if((resource_attributes['k8s.namespace.name']) != '', resource_attributes['k8s.namespace.name'], resource_attributes['service.namespace']) AS namespace,
            if((resource_attributes['deployment.environment.name']) != '', resource_attributes['deployment.environment.name'], if((resource_attributes['deployment.environment']) != '', resource_attributes['deployment.environment'], resource_attributes['env'])) AS environment,
            lower(severity_text) AS severity_text,
            toUInt16(least(intDiv(greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0) + 86399999999, 86400000000), 3650)) AS retention_days
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text
  SQL
  override = try(local.deployment.overrides["logs34_to_volume_buckets"], {})

  depends_on = [
    module.logs34_family,
    module.logs_volume_buckets_family,
  ]
}
