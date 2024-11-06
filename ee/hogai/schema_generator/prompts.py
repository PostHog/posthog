group_mapping_prompt = """
Here is the group mapping:
{{group_mapping}}
"""

plan_prompt = """
Here is the plan:
{{plan}}
"""

new_plan_prompt = """
Here is the new plan:
{{plan}}
"""

question_prompt = """
Answer to this question: {{question}}
"""

failover_output_prompt = """
Generation output:
```
{{output}}
```

Exception message:
```
{{exception_message}}
```
"""

failover_prompt = """
The result of the previous generation raised the Pydantic validation exception.

{{validation_error_message}}

Fix the error and return the correct response.
"""
