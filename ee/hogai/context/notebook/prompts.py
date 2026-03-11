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
""".strip()
