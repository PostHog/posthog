# Testing expectations

Add at least two test modules:

- `tests/test_<source>_source.py` (source-class level):
  - `source_type`
  - `get_source_config` fields and labels
  - `get_schemas` outputs
  - `validate_credentials` success/failure
  - `source_for_pipeline` argument plumbing
  - for resumable sources: `get_resumable_source_manager` returns a manager bound to the right data class
  - for webhook sources: `create_webhook` / `delete_webhook` / `get_external_webhook_info` behavior, `webhook_resource_map` correctness, `webhook_template` presence
- `tests/test_<source>.py` (transport level):
  - paginator behavior from response headers/body
  - resource generation for incremental vs non-incremental
  - endpoint-specific primary key mapping
  - credential validation status mapping
  - mapper/filter helpers if present
  - fan-out endpoint row format assertions (dict shape + parent identifiers)
  - for dependent-resource fan-out: mock `rest_api_resources`, pass rows with `_<parent>_<field>` keys to exercise parent-field injection and rename behavior
  - expected return schema checks for each declared endpoint in `settings.py`
  - for resumable sources: resume-from-saved-state path (manager returns state, transport uses it as starting point); state is saved after each batch
  - for incremental cursor pagination: the paginator stops once a page predates the watermark, and keeps walking when no watermark is set (first sync)

Prefer behavior tests over config-shape tests. Avoid brittle assertions on internal config dict structure unless they protect a known regression that cannot be asserted via output behavior.

Use parameterized tests for status codes and edge cases. Lean toward over-covering.
