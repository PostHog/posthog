GROUP_MAPPING_PROMPT = """
Here is the group mapping:
{{{group_mapping}}}
""".strip()

PLAN_PROMPT = """
Here is the plan:
{{{plan}}}
""".strip()

NEW_PLAN_PROMPT = """
Here is the new plan:
{{{plan}}}
""".strip()

QUESTION_PROMPT = """
Answer to this question: {{{question}}}
""".strip()

FAILOVER_OUTPUT_PROMPT = """
Generation output:
```
{{{output}}}
```

Exception message:
```
{{{exception_message}}}
```
""".strip()

FAILOVER_PROMPT = """
The result of the previous generation raised the Pydantic validation exception.

{{{validation_error_message}}}

Fix the error and return the correct response.
""".strip()
