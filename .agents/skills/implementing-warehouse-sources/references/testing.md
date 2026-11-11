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
| That an error string matches a key of `get_non_retryable_errors()`, e.g. `assert any(p in msg for p in source.get_non_retryable_errors())` | `test_source_error_contract.py` classifies the real errors of every source             |
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

- `SourceDriver(source, config).run(schema_name, script)` runs an extraction through `source_for_pipeline`, as the pipeline does. It commits the resume cursor as the pipeline does, so a cursor saved after the last row does not persist.
- `scripted_network(script)` covers a call outside an extraction, such as a credential probe or a webhook call. Assert on `network.requests_log`.

```python
result = SourceDriver(MySource(), MySourceConfig(api_key="key")).run(
    "orders",
    [ScriptedResponse(json={"data": [{"id": 1}], "next": "c2"}), ScriptedResponse(json={"data": []})],
    incremental_field="updated_at",
    db_incremental_field_last_value="2024-01-01",
)
assert result.raised is None
assert result.params("cursor") == [None, "c2"]
```

The script answers the requests:

- A list of `ScriptedResponse` answers them in order. A request the script does not answer fails the run.
- `route({path: [...]})` answers each path from its own queue, for a source that mixes endpoints or a token exchange.
- `always(answer)` gives every request the same answer. The answer can be an exception, such as `requests.ConnectionError`.
- A function of the `RecordedRequest` gives the answer for a request that needs logic.

**Retried failures need `always`.**
The real stack retries a 429, a 5xx and a dropped connection.
A list with one such answer runs out on the retry and fails with `UnexpectedRequest`.
Use `always(...)`, and assert the set of paths, not the request count.

The keywords after the script go to `source_inputs`: `incremental_field`, `db_incremental_field_last_value`, `should_use_incremental_field`, `api_version` and `logger`.
`should_use_incremental_field` follows `incremental_field`. Set it to `False` for a full refresh on a schema with an incremental field.
`resume_state=` starts the run from a cursor that an earlier attempt saved.

The result holds:

| Field                               | What it holds                                                                                         |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `rows`, `items`                     | The rows the source yielded, flat or as yielded                                                       |
| `requests`, `paths`, `params(name)` | What went on the wire, in order                                                                       |
| `raised`                            | The error the run raised, or `None`. The driver catches it, so assert on it                           |
| `saved_states`, `committed_states`  | Every cursor the source saved, and each cursor that persisted                                         |
| `final_state`, `completed_state`    | The cursor at the end of the run, and after the `on_complete` hook. `None` when the source cleared it |
| `response`                          | The `SourceResponse`: name, primary keys, partitioning, sort mode                                     |
| `session_options`                   | The keyword arguments of each `make_tracked_session` call, such as `redact_values`                    |

The driver answers the webhook checks as for a schema with no webhook, so a webhook source polls the API.
A test that needs the webhook path patches `WebhookSourceManager.webhook_enabled` itself, and the driver keeps that answer.
A test that touches the database fails with `DatabaseBlockedError`.

`sources/zylo/tests/test_zylo.py` shows the pattern.
For a source built on a vendor SDK, mock the SDK client instead.

Do not patch `make_tracked_session`, mock `ResumableSourceManager`, or patch a private name in `sources/common`.
Each one lets a test pass against wrong behavior, and `posthog/test/repo_invariants/test_warehouse_source_test_shapes.py` fails a new test file that does it.
Its baselines list the files that still do, and may only get shorter.
When you move a listed file onto the driver, run `PYTHONPATH=. python posthog/test/repo_invariants/test_warehouse_source_test_shapes.py` to remove it from the baseline.

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
