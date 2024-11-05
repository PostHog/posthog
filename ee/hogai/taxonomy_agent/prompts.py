react_definitions_prompt = """
Here are the event names.
{{events}}
"""

react_scratchpad_prompt = """
Thought: {{agent_scratchpad}}
"""

react_user_prompt = """
Answer the following question as best you can.
Question: What events, properties and/or property values should I use to answer this question "{{question}}"?
"""

react_follow_up_prompt = """
Improve the previously generated plan based on the feedback: {{feedback}}
"""

react_missing_action_prompt = """
Your previous answer didn't output the `Action:` block. You must always follow the format described in the system prompt.
"""

react_missing_action_correction_prompt = """
{{output}}
Action: I didn't output the `Action:` block.
"""

react_malformed_json_prompt = """
Your previous answer had a malformed JSON. You must return a correct JSON response containing the `action` and `action_input` fields.
"""

react_pydantic_validation_exception_prompt = """
The action input you previously provided didn't pass the validation and raised a Pydantic validation exception.

<pydantic_exception>
{{exception}}
</pydantic_exception>

You must fix the exception and try again.
"""
