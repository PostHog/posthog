# Which cell tags the agent may author, chosen by the notebook run endpoint's own flag gate. Both
# the create_notebook tool description and the inline-AI notebook context render one of these, so
# the two surfaces cannot tell the agent different things about the same notebook.
SQL_V2_CELL_GUIDANCE = """- Component tags such as `<Query … />`, `<SQLV2 … />`, and `<PythonV2 … />` render a `title` prop in their block header. Keep the titles already there, and give any tag you add a short one saying what it shows, so a reader can skim the notebook without opening each block
- `<SQLV2 />` and `<PythonV2 />` carry their body in a `code` prop holding the SQL or Python as a string. Only `<Query />` takes a `query` prop holding a query object, so never give a code cell a `query` prop"""

LEGACY_CELL_GUIDANCE = """- Component tags such as `<Query … />` render a `title` prop in their block header. Keep the titles already there, and give any tag you add a short one saying what it shows, so a reader can skim the notebook without opening each block
- `<Query />` carries its body in a `query` prop, never a code string. Give the prop two brace pairs: the outer pair marks an expression and the inner pair is the JSON object. Write `<Query title="Signups by day" query={{"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "SELECT ..."}}} />`. One brace pair parses as a string, and the cell then renders empty with no error
- A SQL `<Query />` must wrap its `HogQLQuery` in a node. Use `DataTableNode` for a result table, or `DataVisualizationNode` with a `display` such as `"ActionsBar"` for a chart. A bare `HogQLQuery` does not render
- Do not add `<SQLV2 />` or `<PythonV2 />` cells. This project cannot run them, so their Run button always fails. Write new SQL as a `<Query />` cell instead"""


WIDGET_CELL_GUIDANCE = """- Generated widgets are available. When the user asks to add a widget or custom interactive visualization, insert `<Widget title="Interactive visualization" prompt="Describe the requested visualization here" />` as notebook markdown, outside a code fence
- Put the user's requirements in `prompt`. Use the `Widget` tag, not `GenUI` or `GeneratedWidget`. Do not write the generated source or invent artifact IDs
- Return the Widget tag directly to insert it, without backticks. If the user explicitly asks to see the tag's syntax instead of inserting a widget, use a code fence with the `text` language
- Widgets infer their inputs from the notebook's SQL and Python dataframe cells. Do not add an `inputs` prop. Add data cells only when needed and when the cell guidance above allows them; widgets can also work without dataframes
- Inserting a Widget block does not generate it. Tell the user to click Generate widget in its settings. All notebook dataframes must have completed runs before generation. Do not claim the widget has been generated merely because you inserted the block"""


def cell_guidance_prompt(*, sql_v2_enabled: bool, widgets_enabled: bool) -> str:
    cell_guidance = SQL_V2_CELL_GUIDANCE if sql_v2_enabled else LEGACY_CELL_GUIDANCE
    if widgets_enabled:
        return f"{cell_guidance}\n{WIDGET_CELL_GUIDANCE}"
    return f"{cell_guidance}\n- Generated widgets are unavailable for this user. Do not add new `<Widget />` cells. Preserve existing widgets when editing unrelated content"


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

Notebook SQL editor nodes are represented as query definitions with `kind = "DataVisualizationNode"` and
`source.kind = "HogQLQuery"`. In those nodes, `source.query` is the SQL text and `source.filters` stores date,
test-account, and property filters that are applied through `{filters}` placeholders in the SQL. When changing the
time range or global property filters for a notebook SQL node, preserve `{filters}` in `source.query` and update
`source.filters` instead of replacing the placeholder with explicit SQL conditions.
""".strip()
