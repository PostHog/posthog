GROUP_MAPPING_PROMPT = """
Here is the group mapping:
{{group_mapping}}
"""

PLAN_PROMPT = """
Here is the plan:
{{plan}}
"""

NEW_PLAN_PROMPT = """
Here is the new plan:
{{plan}}
"""

QUESTION_PROMPT = """
Answer to this question: {{question}}
"""

FAILOVER_OUTPUT_PROMPT = """
Generation output:
```
{{output}}
```

Exception message:
```
{{exception_message}}
```
"""

FAILOVER_PROMPT = """
The result of the previous generation raised the Pydantic validation exception.

{{validation_error_message}}

Fix the error and return the correct response.
"""
