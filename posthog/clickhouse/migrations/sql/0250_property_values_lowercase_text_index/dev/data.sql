ALTER TABLE property_values DROP INDEX IF EXISTS idx_property_value

ALTER TABLE property_values ADD INDEX IF NOT EXISTS idx_property_value property_value TYPE text(tokenizer = ngrams(3), preprocessor = lower(property_value)) GRANULARITY 1

ALTER TABLE property_values MATERIALIZE INDEX idx_property_value
