RESPONSE_FORMATS_PROMPT = """
<response_formats>
Formats of responses
1. Question Response Format
When you need clarification or determines that additional information is required, you should return a response in the following format:
{
    "request": "Your clarifying question here."
}
2. Filter Response Format
Once all necessary data is collected, the agent should return the filter in this structured format:
{
    "data": {
        "date_from": "<date_from>",
        "date_to": "<date_to>",
        "duration": [{"key": "duration", "type": "recording", "value": <duration>, "operator": "gt"}],  // Use "gt", "lt", "gte", "lte"
        "filter_group": {
            "type": "<FilterLogicalOperator>",
            "values": [
            {
                "type": "<FilterLogicalOperator>",
                "values": [
                    {
                        "key": "<key>",
                        "type": "<PropertyFilterType>",
                        "value": ["<value>"],
                        "operator": "<PropertyOperator>"
                    },
                ],
                ...
            },
        ]
    }
}

Notes:
1. Replace <date_from> and <date_to> with valid date strings.
2. <FilterLogicalOperator>, <PropertyFilterType>, and <PropertyOperator> should be replaced with their respective valid values defined in your system.
3. The filter_group structure is nested. The inner "values": [] array can contain multiple items if more than one filter is needed.
4. Ensure that the JSON output strictly follows these formats to maintain consistency and reliability in the filtering process.

WHEN GENERATING A FILTER BASED ON MORE THAN ONE PROPERTY ALWAYS MAKE SURE TO KEEP THE OLD FILTERS. NEVER REMOVE ANY FILTERS.
</response_formats>

""".strip()

TOOL_USAGE_PROMPT = """

## Tool Usage Rules
1. **Property Discovery Required**: Use tools to find properties.
2. Users can be looking for properties related to PERSON, SESSION, ORGANIZATION, or EVENT. EVENTS ARE NOT ENTITIES. THEY HAVE THEIR OWN PROPERTIES AND VALUES.

2. **Tool Workflow**:
   - Infer if the user is asking for a person, session, organization, or event property.
   - Use `retrieve_entity_properties` to discover available properties for an entity such as person, session, organization, etc.
   - Use `retrieve_entity_property_values` to get possible values for a specific property related to person, session, organization, etc.
   - Use `retrieve_event_properties` to discover available properties for an event
   - Use `retrieve_event_property_values` to get possible values for a specific property related to event.
   - Use `ask_user_for_help` when you need clarification
   - Use `final_answer` only when you have complete filter information
   - *CRITICAL*: Call the event tools if you have found a property related to event, do not call the entity tools.
   - *CRITICAL*: DO NOT CALL A TOOL FOR THE SAME ENTITY, EVENT, OR PROPERTY MORE THAN ONCE. IF YOU HAVE NOT FOUND A MATCH YOU MUST TRY WITH THE NEXT BEST MATCH.

3. **When to Ask for Help**:
   - No properties found for the entity/group
   - Cannot infer the correct entity/group type
   - Property values don't match user's request
   - Any ambiguity in the user's request

4. **Value Handling**: CRITICAL: If found values aren't what the user asked for or none are found, YOU MUST USE THE USER'S ORIGINAL VALUE FROM THEIR QUERY. But if the user has not given a value then you ask the user for clarification.

5. **Multi-Filter Example**: If user mentions "mobile users who completed signup":
   - Filter 1: Infer entity type "person" for "mobile" → find $device_type property → get values → use "Mobile"
   - Filter 2: Infer entity type "event" for "signup" → find $signup_event → get event properties if needed
   - Combine both filters with AND logic
   - Use `final_answer` only when ALL filters are processed

6. Use the output of the tools to build the filter. Merge the results for each filter component into a single filter.

""".strip()

GROUPS_PROMPT = """
<groups>
These groups are also used for filtering.
This is the list of all the groups that this user can generate filters for:
{{#groups}}, {{.}}{{/groups}}
If the user mentions a group that is not in this list you MUST infer the most similar group to the one the user is referring to.
</groups>
""".strip()

HUMAN_IN_THE_LOOP_PROMPT = """
<human_in_the_loop>

Ask the user for clarification if:
- The user's question is ambiguous.
- You can't find matching events or properties.
- You can't find matching property values.
- You're unable to build a filter that effectively answers the user's question.
- Use the `ask_user_for_help` tool to ask the user for clarification.

</human_in_the_loop>
""".strip()

FILTER_OPTIONS_ITERATION_LIMIT_PROMPT = """I've tried several approaches but haven't been able to find the right filtering options. Could you please be more specific about what kind of filters you're looking for? For example:
- What type of events or actions are you interested in?
- What properties do you want to filter on?
- Are you looking for specific values or ranges?"""

REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT = """I encountered an error while validating the tool input. Here's what went wrong:
{{{exception}}}

Please help me understand what you're looking for more clearly, and I'll try again.""".strip()


USER_FILTER_OPTIONS_PROMPT = """
Goal: {{{change}}}

Current filters: {{{current_filters}}}

DO NOT CHANGE THE CURRENT FILTERS. ONLY ADD NEW FILTERS or update the existing filters.
""".strip()
