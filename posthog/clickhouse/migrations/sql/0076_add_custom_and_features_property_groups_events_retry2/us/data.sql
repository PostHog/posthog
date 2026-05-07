ALTER TABLE events ADD COLUMN IF NOT EXISTS properties_group_custom Map(String, String)

ALTER TABLE events ADD COLUMN IF NOT EXISTS properties_group_feature_flags Map(String, String)
