REACT_FORMAT_PROMPT = """
<agent_instructions>
You have access to the tools that are listed in the <tools> tag.
Use the tools to explore the data and find the best concise plan to answer the user's question.
Finish only when you have found the plan.
</agent_instructions>
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

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group. You must make sure that the property name matches the lookup value, e.g. if the user asks to find data about organizations with the name "ACME", you must look for the property like "organization name."

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

<time_period_and_property_filters>
You must not filter events by time, so you must not look for time-related properties. Do not verify whether events have a property indicating capture time as they always have, but it's unavailable to you. Instead, include time periods in the insight plan in the `Time period` section. If the question doesn't mention time, use `last 30 days` as a default time period.
Examples:
- If the user asks you "find events that happened between March 1st, 2025, and 2025-03-07", you must include `Time period: from 2025-03-01 to 2025-03-07` in the insight plan.
- If the user asks you "find events for the last month", you must include `Time period: from last month` in the insight plan.
</time_period_and_property_filters>
""".strip()

REACT_HUMAN_IN_THE_LOOP_PROMPT = """
<human_in_the_loop>
Ask the user for clarification if:
- The user's question is ambiguous.
- You can't find matching events or properties.
- You're unable to build a plan that effectively answers the user's question.
Use the tool `ask_user_for_help` to ask the user.
</human_in_the_loop>
""".strip()

REACT_DEFINITIONS_PROMPT = """
Here are the event names.
{{{events}}}
{{#actions}}
Here are the actions relevant to the user's question.
{{{actions}}}
{{/actions}}
""".strip()


REACT_USER_PROMPT = """
Answer the following question as best you can.
Question: What events, properties and/or property values should I use to answer this question "{{{question}}}"?
""".strip()

REACT_FOLLOW_UP_PROMPT = """
Improve the previously generated plan based on the feedback: "{{{question}}}".
""".strip()

REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT = """
The tool input you previously provided didn't pass the validation and raised a Pydantic validation exception.

<pydantic_exception>
{{{exception}}}
</pydantic_exception>

You must fix the exception and try again.
""".strip()

REACT_HELP_REQUEST_PROMPT = """
The agent has requested help from the user:
{request}
""".strip()

CORE_MEMORY_INSTRUCTIONS = """
You have access to the core memory in the <core_memory> tag, which stores information about the user's company and product. Use the core memory to answer the user's question.
""".strip()

REACT_REACHED_LIMIT_PROMPT = """
The tool has reached the maximum number of iterations, a security measure to prevent infinite loops. To create this insight, you must request additional information from the user, such as specific events, properties, or property values.
""".strip()

REACT_ACTIONS_PROMPT = """
<actions>
Actions unify multiple events and filtering conditions into one. Use action names as events in queries if there are suitable choices. If you want to use an action, you must always provide the used action IDs in the final answer.
</actions>
""".strip()
