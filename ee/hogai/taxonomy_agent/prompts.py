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

REACT_PROPERTY_FILTERS_PROMPT = """
<property_filters>
Use property filters to provide a narrowed results. Only include property filters when they are essential to directly answer the user’s question. Avoid adding them if the question can be addressed without additional segmentation and always use the minimum set of property filters needed to answer the question. Properties have one of the four types: String, Numeric, Boolean, and DateTime.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you must:
- **Prioritize properties directly related to the context or objective of the user's query.** Avoid using properties for identification like IDs because neither the user nor you can retrieve the data. Instead, prioritize filtering based on general properties like `paidCustomer` or `icp_score`.
- **Ensure that you find both the property group and name.** Property groups must be one of the following: event, person, session{{#groups}}, {{.}}{{/groups}}.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`). The operators are listed below.
- If the operator requires a value, use the tool to find the property values. Verify that you can answer the question with given property values. If you can't, try to find a different property or event.
- You set logical operators to combine multiple properties of a single series: AND or OR.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group. You must make sure that the property name matches the lookup value, e.g. if the user asks to find data about organizations with the name "ACME", you must look for the property like "organization name".

If the user asks for a specific timeframe, you must not look for a property and include it in the plan, as the next steps will handle it for you.

Supported operators for the String or Numeric types are:
- equals
- doesn't equal
- contains
- doesn't contain
- matches regex
- doesn't match regex
- is set
- is not set

Supported operators for the DateTime type are:
- equals
- doesn't equal
- greater than
- less than
- is set
- is not set

Supported operators for the Boolean type are:
- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal which can take one or more values.
</property_filters>
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
