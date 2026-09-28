# JSONCleanPostHogEventProperties Stateless Fixtures

These fixtures cover PostHog event property cleanup before casting to native ClickHouse JSON. Scalar and array values are preserved for ClickHouse to infer on dynamic paths. Malformed JSON must fail processing; a `$feature_flags` value that is not an object becomes an empty map and is recorded as stringified JSON in `$unparseable_properties`.
