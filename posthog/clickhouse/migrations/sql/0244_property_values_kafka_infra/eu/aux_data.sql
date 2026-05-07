CREATE TABLE IF NOT EXISTS property_values_distributed
(
    `team_id` Int64 CODEC(DoubleDelta, ZSTD(1)),
    `property_type` LowCardinality(String),
    `property_key` LowCardinality(String),
    `property_value` String,
    `property_count` SimpleAggregateFunction(sum, UInt64),
    `last_seen` SimpleAggregateFunction(max, DateTime) DEFAULT now()
    
) ENGINE = Distributed('aux', 'default', 'property_values')
