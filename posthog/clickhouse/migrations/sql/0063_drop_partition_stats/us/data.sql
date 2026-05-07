DROP TABLE IF EXISTS `default`.events_plugin_ingestion_partition_statistics ON CLUSTER 'posthog' SYNC

DROP TABLE IF EXISTS `default`.events_plugin_ingestion_partition_statistics_mv ON CLUSTER 'posthog' SYNC

DROP TABLE IF EXISTS `default`.events_plugin_ingestion_overflow_partition_statistics_mv ON CLUSTER 'posthog' SYNC

DROP TABLE IF EXISTS `default`.session_recording_events_partition_statistics_mv ON CLUSTER 'posthog' SYNC
