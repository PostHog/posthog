react_format_prompt = """
You have access to the following tools:
{{tools}}

Use a JSON blob to specify a tool by providing an action key (tool name) and an action_input key (tool input).

Valid "action" values: {{tool_names}}

Provide only ONE action per $JSON_BLOB, as shown:

```
{
  "action": $TOOL_NAME,
  "action_input": $INPUT
}
```

Follow this format:

Question: input question to answer
Thought: consider previous and subsequent steps
Action:
```
$JSON_BLOB
```
Observation: action result
... (repeat Thought/Action/Observation N times)
Thought: I know what to respond
Action:
```
{
  "action": "final_answer",
  "action_input": "Final response to human"
}
```
""".strip()

react_format_reminder_prompt = """
Begin! Reminder that you must ALWAYS respond with a valid JSON blob of a single action. Use tools if necessary. Respond directly if appropriate. Format is Action:```$JSON_BLOB``` then Observation.
""".strip()

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
