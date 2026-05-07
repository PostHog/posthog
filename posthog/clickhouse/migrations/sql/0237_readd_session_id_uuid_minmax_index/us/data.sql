ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$session_id_uuid` `$session_id_uuid`
TYPE minmax
GRANULARITY 1
