PROPERTY_FILTER_TYPES_PROMPT = """
<property_filter_types>
PostHog users can filter their data using various properties and values.
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
</property_filter_types>
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
