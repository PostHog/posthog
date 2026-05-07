ALTER TABLE sharded_events
    ADD COLUMN IF NOT EXISTS `properties_map_ephemeral` Map(String, String) EPHEMERAL CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'),
    ADD COLUMN IF NOT EXISTS `person_properties_map_ephemeral` Map(String, String) EPHEMERAL CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)');
