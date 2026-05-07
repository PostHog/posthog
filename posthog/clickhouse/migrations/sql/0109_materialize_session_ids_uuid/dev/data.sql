ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))

ALTER TABLE events
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128)
