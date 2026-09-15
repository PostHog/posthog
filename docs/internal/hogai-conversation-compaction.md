# PostHog AI conversation compaction

The built-in agent compacts its active conversation when the token count exceeds 400,000. The summarizer provides continuity while a small tail of recent messages preserves the latest exchanges.

## Conversation window

The next model input starts with the new summary, followed by any required todo and mode reminders. The current request remains in the retained tail or is copied before it. The tail contains at most 16 messages and 2,048 estimated tokens; context messages count toward this budget too. A result too large for that tail is represented by the summary.

Window boundaries identify either human or assistant messages by ID. Stored history and artifact references remain available outside the active window. Compaction does not reset the tool-call counter, which still limits the agent loop.

Tests must inspect the messages sent to the model. A summary appearing in stored state does not prove it is inside the active window.

## SQL result previews

Native agent SQL execution and SQL-backed insight reads opt into a 64,000-character preview budget. That budget covers the result table, query warnings, and preview notice; query definitions and surrounding context prompts are separate. Cells, including plain text, are shortened to at most 500 characters including the marker. The formatter retains complete rows in order and reports how many returned rows are shown. It reports when a header or first row is too wide to display.

The preview is incomplete when cells are shortened or rows are omitted. Omitted data is not evidence that an event, property, or value is absent. The agent can select fewer columns, aggregate, filter, or paginate with a stable ordering to inspect more data. The existing visualization artifact preserves the query definition and chart settings; it does not store a snapshot of query results.

If table formatting fails, the JSON fallback receives the same output budget and explicitly marks an incomplete preview. Raw query responses are not modified.

## MCP compatibility

The new preview budget is opt-in at native agent call sites. Shared formatters and query execution default to no total preview budget. MCP tools and the synchronous formatter used by MCP endpoints retain their existing behavior, including existing JSON-cell truncation and the `truncate=false` option. The new plain-text cell limit does not apply to them, including MCP requests attributed to a first-party agent.
