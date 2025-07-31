PROPERTY_TYPES_PROMPT = """
<context>
<property_types>
In order to perform the task you are given, you need to understand the properties of events and entities, and to retrieve the values of properties. The output of your responses can later be used for different tasks such as creating filters or queries.
Properties are always associated with an event or entity. When looking for properties, determine first which event or entity a lookup property is associated with.

**CRITICAL**: There are two main categories of properties - ENTITY properties and EVENT properties. They use different tools.

<entity>
**ENTITY PROPERTIES** (use `retrieve_entity_properties` and `retrieve_entity_property_values`):

<person>
- Person Properties:
    Are associated with a person. For example, email, name, is_signed_up etc.
    Use the "name" field from the Person properties array (e.g., name, email).
    Example: If filtering on email, you might use the key email.
    Use `retrieve_entity_properties` with entity="person" to get the list of all available person properties.
</person>

<session>
- Session Properties:
    Are associated with a session. For example, $start_timestamp, $entry_current_url, session duration etc.
    Use the "name" field from the Session properties array (e.g., $start_timestamp, $entry_current_url).
    Example: If filtering based on the session start time, you might use the key $start_timestamp.
    Use `retrieve_entity_properties` with entity="session" to get the list of all available session properties.
</session>

<group>
- Group Properties:
    PostHog users can group these events into custom groups. For example organisation, instance, account etc.
    This is the list of all the groups that this user can generate filters for:
    {{#groups}}{{.}}{{^last}}, {{/last}}{{/groups}}
    If the user mentions a group that is not in this list you MUST infer the most similar group to the one the user is referring to.
    Use `retrieve_entity_properties` with entity="[group_name]" to get the list of all available group properties.
</group>
</entity>
<events>
**EVENT PROPERTIES** (use `retrieve_event_properties` and `retrieve_event_property_values`):
- Event Properties:
    Properties of specific events. For example, if someone says "users who completed signup", you need to find the "signup" event and then get its properties.
    Use `retrieve_event_properties` with event_name="signup" to get properties of the signup event.
    Example: For filtering on the user's browser during signup, you might use the key $browser from the signup event.
Here is a non-exhaustive list of known event names:
{{{events}}}

If you find the event name the user is asking for in the list, use it to retrieve the event properties.
</events>
</property_types>
</context>
""".strip()

TAXONOMY_TOOL_USAGE_PROMPT = """
<tool_usage>
## Tool Usage Rules
1. **Property Discovery Required**: Use tools to find properties.
2. **CRITICAL DISTINCTION**: EVENTS ARE NOT ENTITIES. THEY HAVE THEIR OWN PROPERTIES AND VALUES.

3. **Tool Workflow**:
   - **For ENTITY properties** (person, session, organization, groups): Use `retrieve_entity_properties` and `retrieve_entity_property_values`
   - **For EVENT properties** (properties of specific events like pageview, signup, etc.): Use `retrieve_event_properties` and `retrieve_event_property_values`
   - Use `ask_user_for_help` when you need clarification
   - Use `final_answer` only when you have complete information
   - *CRITICAL*: NEVER use entity tools for event properties. NEVER use event tools for entity properties.
   - *CRITICAL*: DO NOT CALL A TOOL FOR THE SAME ENTITY, EVENT, OR PROPERTY MORE THAN ONCE. IF YOU HAVE NOT FOUND A MATCH YOU MUST TRY WITH THE NEXT BEST MATCH.

4. **Value Handling**: CRITICAL: If found values aren't what the user asked for or none are found, YOU MUST USE THE USER'S ORIGINAL VALUE FROM THEIR QUERY. But if the user has not given a value then you ask the user for clarification.

</tool_usage>
""".strip()

HUMAN_IN_THE_LOOP_PROMPT = """
When you need clarification or determines that additional information is required, you can use the `ask_user_for_help` tool.
**When to Ask for Help**:
- Cannot infer the correct entity/group/event type
- No properties found for the entity/group/event
- Property values don't match user's request
""".strip()

USER_PROMPT = """
Goal: {{{change}}}

Current filters: {{{current_filters}}}

DO NOT CHANGE THE CURRENT FILTERS. ONLY ADD NEW FILTERS or update the existing filters.
""".strip()

REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT = """
The action input you previously provided didn't pass the validation and raised a Pydantic validation exception.
<pydantic_exception>
{{{exception}}}
</pydantic_exception>
You must fix the exception and try again.
""".strip()

ITERATION_LIMIT_PROMPT = """I've tried several approaches but haven't been able to find the right options. Could you please be more specific about what kind of properties you're looking for? For example:
- What type of events or actions are you interested in?
- What properties do you want to filter on?
- Are you looking for specific values or ranges?"""
