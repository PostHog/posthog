# JSONCleanPostHogEventProperties Stateless Fixtures

These fixtures cover PostHog event property cleanup before casting to typed ClickHouse JSON. Scalar values are preserved for ClickHouse to cast to `Nullable(String)`, and top-level objects and arrays become strings of compact JSON text with sorted keys. Malformed JSON must fail processing; a `$feature_flags` value that is not an object becomes an empty map and is recorded as stringified JSON in `$unparseable_properties`.
