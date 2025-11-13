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

Here is a non-exhaustive list of known **EVENT NAMES**:
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

4. **Property Value Matching**:
- IMPORTANT: If tool call returns property values that are related BUT NOT SYNONYMS to the user's requested value: USE USER'S ORIGINAL VALUE.
For example, if the user asks for $browser to be "Chrome" and the tool call returns '"Firefox", "Safari"', use "Chrome" as the property value. Since "Chrome" is related to "Firefox" and "Safari" since they are all browsers.
- IMPORTANT: If tool call returns property values that are synonyms, typos, or a variant of the user's requested value: USE FOUND VALUES
For example the user asks for the city to be "New York" and the tool call returns "New York City", "NYC", use "New York City" as the property value. Since "New York" is related to "New York City" and "NYC" since they are all variants of New York.

5. **Optimization**:
- Remember that you are able to make parallel tool calls. This is a big performance improvement. Whenever it makes sense to do so, call multiple tools at once.
- Always aim to optimize your tool calls. This will help you find the correct properties and values faster.

6. **Filter Completion**:
- Always aim to complete the filter as much as possible. This will help you meet the user's expectations.
- If you have found most of the properties and values but you are still missing some, return the filter that you have found so far. The user can always ask you to add more properties and values later.
- Be careful though, if you have not found most of the properties and values, you should use the `ask_user_for_help` tool to ask the user for more information.
Example: If the user asks to filter for location, url type, date and browser type, and you could not find anything about the url you can return the filter you found.


- If the tool call returns no values, you can retry with the next best property or entity.
</tool_usage>
""".strip()

HUMAN_IN_THE_LOOP_PROMPT = """
When you need clarification or determines that additional information is required, you can use the `ask_user_for_help` tool.
**When to Ask for Help**:
- Cannot infer the correct entity/group/event type.
- Cannot infer the correct property for the entity/group/event.
- No properties found for the entity/group/event.
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
- Are you looking for specific values or ranges?"""
