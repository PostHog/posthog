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

When the user asks you to add to, edit, or otherwise update one of these notebooks, you must call `create_notebook`
with `artifact_id` set to that notebook's `short_id` above. Calling `create_notebook` without `artifact_id` creates
a brand-new transient notebook and leaves the saved notebook the user is looking at unchanged — users have repeatedly
been confused when Max created a new notebook instead of updating the one they had open, so always pass `artifact_id`
unless the user explicitly asks for a fresh notebook.

Notebook SQL editor nodes are represented as query definitions with `kind = "DataVisualizationNode"` and
`source.kind = "HogQLQuery"`. In those nodes, `source.query` is the SQL text and `source.filters` stores date,
test-account, and property filters that are applied through `{filters}` placeholders in the SQL. When changing the
time range or global property filters for a notebook SQL node, preserve `{filters}` in `source.query` and update
`source.filters` instead of replacing the placeholder with explicit SQL conditions.
""".strip()
