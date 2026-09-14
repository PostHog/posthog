# MCP model identification

The MCP analytics model chart shows the six most-used reported model identifiers.
Other models combines the remaining identifiers and counts toward the identified percentage.
Unknown counts calls with no captured model identifier.
The coverage summary separates unknown calls from the model ranking.
It remains visible when every call is unknown, showing 0% identified coverage.
The ranking shows named models by call count, followed by Other models; all percentages use all calls, including unknown calls, as the denominator.
Show all models expands a table of individual reported identifiers, loaded on demand in pages of 50.
The table uses the dashboard filters and keeps unknown calls in the percentage denominator.
Unknown calls stay in the coverage summary, and changing filters resets the expanded table.
For a date range ending now, the first page fixes the time bounds for subsequent pages and retries.
Late-arriving events within those bounds can still affect counts; the table is not a database snapshot.
The query's `includeAllModels` option enables this ungrouped view; `limit` (1 to 100) and `offset` select a page, and `hasMore` indicates another page is available.
Explore models opens a Trends table that trims model identifiers and groups missing or blank values under Unknown, with the dashboard's date range, property filters, and test-account exclusion preserved.
The table can show up to 50 identifiers before grouping the remaining values.
Identifiers come from client metadata or the agent's self-report; the identified percentage measures reporting coverage, not verified model identity.

PostHog's MCP server asks for `llm_model` on advertised tools and prefers recognized client metadata when available.
Agents can report `unknown` when they do not know their model.
Calls continue to work when the argument is omitted or invalid.

## Investigating unknown calls

When no model is captured, PostHog's MCP server adds `$mcp_llm_model_missing_reason` to `$mcp_tool_call`:

| Value           | Meaning                                                                                                                |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `missing`       | The call omitted the `llm_model` argument.                                                                             |
| `unknown`       | The argument was `unknown`, ignoring case and surrounding whitespace.                                                  |
| `invalid`       | The argument was blank or was not a string.                                                                            |
| `not_captured`  | A nonempty report was supplied but the analytics SDK did not capture it, for example when the tool owns that argument. |
| `capture_error` | Analytics preparation failed.                                                                                          |

The reason describes the model argument only after client metadata and self-report resolution produced no model.
A model resolved from client metadata has no missing reason, even if the agent supplied `unknown` or an invalid argument.
Only the reason is recorded; rejected values and exception messages are not added to this property.

Break down unknown calls by this property and client over a period after deployment.
Use `missing` to investigate callers with older tool schemas or scripts that do not supply a model.
Use `unknown` to find clients where agents lack model identity and client-supplied metadata would help.
Do not infer a model from the client name or assume a scripted call has a calling model.

Historical events and other instrumented MCP servers may have no missing reason.
That absence does not mean the agent reported `unknown`.
This instrumentation does not backfill historical events or change the model chart's counts.
