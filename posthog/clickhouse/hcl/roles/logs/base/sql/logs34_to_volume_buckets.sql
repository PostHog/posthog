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
      if(
        (resource_attributes['k8s.namespace.name']) != '',
        resource_attributes['k8s.namespace.name'],
        resource_attributes['service.namespace']
      ) AS namespace,
      if(
        (resource_attributes['deployment.environment.name']) != '',
        resource_attributes['deployment.environment.name'],
        if(
          (resource_attributes['deployment.environment']) != '',
          resource_attributes['deployment.environment'],
          resource_attributes['env']
        )
      ) AS environment,
      lower(severity_text) AS severity_text,
      toUInt16(
        least(
          intDiv(
            greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0) + 86399999999,
            86400000000
          ),
          3650
        )
      ) AS retention_days
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name, namespace, environment, severity_text
