REACT_FORMAT_PROMPT = """
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

REACT_FORMAT_REMINDER_PROMPT = """
Begin! Reminder that you must ALWAYS respond with a valid JSON blob of a single action. Use tools if necessary. Respond directly if appropriate. Format is Action:```$JSON_BLOB``` then Observation.
""".strip()

REACT_DEFINITIONS_PROMPT = """
Here are the event names.
{{events}}
"""

REACT_SCRATCHPAD_PROMPT = """
Thought: {{agent_scratchpad}}
"""

REACT_USER_PROMPT = """
Answer the following question as best you can.
Question: What events, properties and/or property values should I use to answer this question "{{question}}"?
"""

REACT_FOLLOW_UP_PROMPT = """
Improve the previously generated plan based on the feedback: {{feedback}}
"""

REACT_MISSING_ACTION_PROMPT = """
Your previous answer didn't output the `Action:` block. You must always follow the format described in the system prompt.
"""

REACT_MISSING_ACTION_CORRECTION_PROMPT = """
{{output}}
Action: I didn't output the `Action:` block.
"""

REACT_MALFORMED_JSON_PROMPT = """
Your previous answer had a malformed JSON. You must return a correct JSON response containing the `action` and `action_input` fields.
"""

REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT = """
The action input you previously provided didn't pass the validation and raised a Pydantic validation exception.

<pydantic_exception>
{{exception}}
</pydantic_exception>

You must fix the exception and try again.
"""
