# Testing a warehouse source

The per-source test directories once held about a fifth of the test cases in the monorepo, and every backend PR waited on them.
Most of those cases restated a declaration, re-ran a shared helper, or covered lines another test already covered.
[#113325](https://github.com/PostHog/posthog/pull/113325) deleted them after measuring per-test line coverage.
Write the tests that would have survived that cut, and nothing else.

## The gate

Before you write a test, name the runtime failure it catches that no other test catches.
"Someone edits the constant" is not a runtime failure: the edit changes both halves of the test.
If you cannot name one, do not write the test.

## Do not write these

### Tests that read back a declaration

The assertion compares a value with the line that declares it.
The test can only fail when someone edits both, so it catches nothing.

| Do not assert                                                                                                                 | Why it is already safe                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `lists_tables_without_credentials is True`                                                                                    | `test_static_catalog_sources_can_list_tables_without_credentials` checks it for every source                                           |
| `connection_host_fields == [...]`, or that a host field rejects an internal host                                              | `test_sources_with_a_host_field_refuse_an_internal_host` checks every source with a host field                                         |
| `api_docs_url` is https, `supported_versions`, `default_version`                                                              | `test_every_source_declares_valid_versions` checks every source                                                                        |
| `get_source_config` shape: category, `releaseStatus`, `docsUrl`, field names, which fields are secret                         | `test_every_source_has_a_valid_category` and `test_credential_fields_are_marked_secret` check every source; the rest is a declaration  |
| The set of endpoint names, or each endpoint's primary keys, incremental fields, partition key or page size from `settings.py` | A declaration. Test what the transport does with it instead                                                                            |
| That `canonical_descriptions.py` covers each endpoint, or that `get_documented_tables()` lists them                           | `test_canonical_descriptions_are_keyed_by_schema_name` and `test_documented_tables_match_the_schemas_they_describe` check every source |
| `unreleasedSource is True`                                                                                                    | This locks a finished source hidden. Never write it                                                                                    |

The shared tests live in `sources/tests/test_source_catalog_invariants.py`, `test_source_versions.py` and `test_source_categories.py`.

### Tests that re-run shared framework code

| Do not test                                                                                                                                | Why                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| That an error string matches a key of `get_non_retryable_errors()`, e.g. `assert any(p in msg for p in source.get_non_retryable_errors())` | The test copies the pattern into the message, so it restates the dict                  |
| `get_schemas(names=[...])` filtering, or the sync modes it builds, when `get_schemas` is one `build_endpoint_schemas(...)` call            | `common/test_source_schema.py` covers the helper                                       |
| `get_documented_tables()` output                                                                                                           | The catalog invariants cover it                                                        |
| A `source_for_pipeline` that forwards its config to the transport                                                                          | The forwarding has no branch                                                           |
| The `rest_source` paginators, auth classes, retries or `Retry-After` handling                                                              | `common/rest_source/` tests cover them. Test your source's own paginator subclass only |

### Tests that cover lines another test already covers

A second test that walks the same lines adds runtime cost and no protection.
These were the most common duplicates:

- A "first page" or "single page" paginator test next to a test that already walks two pages to the terminal page.
- A "resume state while there is a next page" test next to a resume test that already saves and loads state.
- A full-refresh test and an incremental test that share every line except one parameter. Use one parameterized test.
- One test per HTTP status when the statuses take the same code path. Parameterize them in one test.

Before you add a case, name the branch or line that only it reaches.

## Write these

### `tests/test_<source>.py`: the transport

This is where most bugs live.
Use parameterized cases. Never use the network.

Run the source against scripted vendor answers with the helpers in `sources/common/testing`.
They answer the real request at the socket, so the test asserts what goes on the wire.

- `SourceDriver(source, config).run(schema_name, script)` runs an extraction through `source_for_pipeline`. The result holds `rows`, `requests`, `saved_states` and `committed_states`.
- `scripted_network(script)` covers a call outside an extraction, such as a credential probe or a webhook call.
- A script is a list of `ScriptedResponse`, or `route({path: [...]})` when the source mixes endpoints. A request the script does not answer fails the run.

`sources/zylo/tests/test_zylo.py` shows the pattern.
For a source built on a vendor SDK, mock the SDK client instead.

Do not patch `make_tracked_session`, mock `ResumableSourceManager`, or patch a private name in `sources/common`.
Each one lets a test pass against wrong behavior, and `posthog/test/repo_invariants/test_warehouse_source_test_shapes.py` fails a new test file that does it.

- **Pagination:** one test that walks at least two pages to the terminal page, and asserts the request parameters of each page. Add the cases where the vendor's termination signal is unusual (an empty page with a cursor, a `has_more` flag that lies).
- **Request shaping:** an incremental request sends the watermark in the vendor's filter and sort; a full refresh sends no watermark. One parameterized test.
- **Ordering:** if the source sorts or windows rows itself, assert the order it yields, because `sort_mode` trusts it.
- **Error mapping:** drive a real vendor response through the transport (status code and body) and assert the error it raises, or the message `validate_credentials` returns. Keep the vendor's verbatim error text in the fixture: it records what the vendor actually sends.
- **Resume:** for a `ResumableSource`, one test that resumes from saved state (`resume_state=`) and one that asserts state is saved before the batch it covers is yielded (`committed_states`).
- **Row shaping:** mappers, type conversions, fan-out parent fields, flattening. Use edge-case inputs such as nulls, nested objects, and timezones.
- **Incremental cursor pagination:** the walk stops once a page predates the watermark, and continues when there is no watermark.

### `tests/test_<source>_source.py`: the source class

Only for branches the source class itself takes.
Many sources need no file here.

- `validate_credentials` that maps a probe result to a message, rejects an unknown schema, or accepts a missing scope at create time: one case per branch.
- `get_schemas` that lists a remote directory, resolves per-version endpoints, or builds qualified names.
- `source_for_pipeline` that raises on an unknown schema, picks between transports, or reads schema metadata.
- A derived value such as a `SourceResponse.name` taken from a storage key. A wrong name writes data where nothing reads it.
- Webhook sources: `create_webhook`, `delete_webhook`, `get_external_webhook_info`, and `webhook_resource_map`.

## Size check

A typical REST source needs one transport module of 10 to 25 parameterized cases and no source-class module.
If a new source's tests are longer than its implementation, look for the patterns above before you push.
