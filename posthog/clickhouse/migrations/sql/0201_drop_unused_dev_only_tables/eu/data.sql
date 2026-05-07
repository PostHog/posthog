DROP TABLE IF EXISTS events_plugin_ingestion_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS events_plugin_ingestion_overflow_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS events_plugin_ingestion_historical_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS session_recording_snapshot_item_events_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS session_recording_snapshot_item_overflow_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_events_plugin_ingestion_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_events_plugin_ingestion_overflow_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_events_plugin_ingestion_historical_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_session_recording_events_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_session_recording_snapshot_item_events_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_session_recording_snapshot_item_overflow_partition_statistics SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS events_plugin_ingestion_partition_statistics_v2 SYNC SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS session_replay_events_v2_test_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS writable_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS sharded_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS log_entries_v2_test_mv SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS kafka_log_entries_v2_test SETTINGS max_table_size_to_drop = 0

DROP TABLE IF EXISTS log_entries_v2_test SYNC SETTINGS max_table_size_to_drop = 0
