ALTER TABLE raw_sessions 
ADD COLUMN IF NOT EXISTS
max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC'))
AFTER max_timestamp
