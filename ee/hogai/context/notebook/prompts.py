NOTEBOOK_CONTEXT_TEMPLATE = """
Notebook: {title}
short_id: {short_id}
created_at: {created_at}
last_modified_at: {last_modified_at}
URL: {url}

{content}
""".strip()

ROOT_NOTEBOOKS_CONTEXT_PROMPT = """
# Notebooks
The user has provided the following notebooks:

{{{notebooks}}}

When the user asks you to change one of these saved notebooks, use `edit_notebook` with exact anchors from the notebook
content. Do not use `create_notebook` to make a copy unless the user explicitly asks for a new notebook.
For complex analyses, inspect values with available data tools first, then use `edit_notebook` to insert markdown plus
query nodes using `<query>` blocks. Prefer old-style HogQLQuery nodes for SQL analysis. Do not use `<hogql>`,
`<ducksql>`, or `<python>` blocks unless the `edit_notebook` tool description says executable notebook cells are enabled
and the user specifically needs them.

Notebook SQL editor nodes are represented as query definitions with `kind = "DataVisualizationNode"` and
`source.kind = "HogQLQuery"`. In those nodes, `source.query` is the SQL text and `source.filters` stores date,
test-account, and property filters that are applied through `{filters}` placeholders in the SQL. When changing the
time range or global property filters for a notebook SQL node, preserve `{filters}` in `source.query` and update
`source.filters` instead of replacing the placeholder with explicit SQL conditions.
""".strip()
