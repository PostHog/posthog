# Customer handoff

A markdown doc CS can send as is. Load writing-user-facing-copy before you write it.

## Shape

```markdown
# Recurring queries worth materializing

One paragraph: the window you looked at (dates, UTC), what the jobs have in common, and what materializing changes for them.

The queries are listed below in order of impact, with SQL you can paste.

## 1. <What the job does> (<MCP `execute-sql` | API>)

What runs today:

- How often it runs, how many queries per pass, and what each returns.
- What fails and how often, with the date range.
- Why it costs what it does, in their terms, such as rereading the same finished period on every run or reading a window that grows every day.

What we suggest:

- The object to create (endpoint or view), its refresh interval, and the SQL below.
- What the caller changes, such as calling the endpoint once per run and filtering the result itself.
- What to change for other variants of the same job.

<SQL, validated on their data>

One or two lines on the validation: rows returned, time to compute, match against their current results.
```

## Rules

- Order items by impact (CPU or failures prevented), and put the path in each heading: `(MCP execute-sql)` or `(API)`.
- Name a specific query in every item. A paste of its key lines with `...` is fine.
- Every number comes from a query you ran in this investigation. Keep the SQL in the scratchpad.
- Use the labels the UI shows today, such as "Save as view" and "Materialize endpoint". Confirm each one on `origin/master` (`git grep -n '<label>' origin/master -- frontend products`) before you write it.
- Leave out internal names: ClickHouse users, clusters, nodes, feature flags, team lists, code paths.
- Replace end-user emails, distinct IDs and person IDs with `<email>` or `<uuid>`.
- Don't suggest async requests as a way around the sync time limit. If they asked about async, answer in their item: async changes how they wait for a result, not how much each run costs, and the fix in that item makes each run cheaper.
- Leave out sections on how materialization works and on queries not worth changing. Answer those in Slack if CS asks.
- No em dashes, no bold, sentence case.
- If the customer has to accept staler data for the savings, say so in that item with the numbers for each refresh interval.
