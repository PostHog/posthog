ALTER TABLE sharded_raw_sessions_v3 MODIFY SETTING parts_to_delay_insert = 250, max_delay_to_insert = 10, parts_to_throw_insert = 1000

DROP TABLE IF EXISTS raw_sessions_v3_mv

DROP TABLE IF EXISTS raw_sessions_v3_recordings_mv
