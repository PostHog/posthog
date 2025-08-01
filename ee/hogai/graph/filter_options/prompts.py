FILTER_OPTIONS_ITERATION_LIMIT_PROMPT = """I've tried several approaches but haven't been able to find the right filtering options. Could you please be more specific about what kind of filters you're looking for? For example:
- What type of events or actions are you interested in?
- What properties do you want to filter on?
- Are you looking for specific values or ranges?"""

FILTER_FIELDS_TAXONOMY_PROMPT = """
<filter_fields_taxonomy>
For the filter fields, you will find information on how to correctly discover the type of the filter field.

<key> Field

- Purpose:
The <key> represents the name of the property on which the filter is applied.

- Type Determination:
The expected data type can be inferred from the property_type field provided in each property object:
- "String" indicates the value should be a string.
- "Numeric" indicates a numeric value.
- "Boolean" indicates a boolean value.
- "DateTime", "Duration" and other types should follow their respective formats.
- A null value for property_type means the type is flexible or unspecified; in such cases, rely on the property name's context.
</key>

<value> Field

- Purpose:
The <value> field is an array containing one or more values that the filter should match.

- Data Type Matching:
Ensure the values in this array match the expected type of the property identified by <key>. For example:
- For a property with property_type "String", the value should be provided as a string (e.g., ["Mobile"]).
- For a property with property_type "Numeric", the value should be a number (e.g., [10]).
- For a property with property_type "Boolean", the value should be either true or false (e.g., [true]).

- Multiple Values:
The <value> array can contain multiple items when the filter should match any one of several potential values.


<supported_operators>
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

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values.
</supported_operators>

</filter_fields_taxonomy>

""".strip()

DATE_FIELDS_PROMPT = """
<date_fields>
Below is a refined description for the date fields and their types:

<date_from>
- Relative Date (Days): Use the format "-Nd" for the last N days (e.g., "last 5 days" becomes "-5d", "yesterday" becomes "-1d").
- Relative Date (Hours): Use the format "-Nh" for the last N hours (e.g., "last 5 hours" becomes "-5h").
- Custom Date: If a specific start date is provided, use the format "YYYY-MM-DD".
- If a date is provided but without a year or month, use the current year and month.
- Default Behavior: If the user does not specify a date range, default to the last 5 days (i.e., use "-5d"). date_from MUST be set.
</date_from>

<date_to>
- Default Value: Set as null when the date range extends to today. Set as null when the user does not specify an end date.
- Custom Date: If a specific end date is required, use the format "YYYY-MM-DD".
</date_to>
</date_fields>
""".strip()

REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT = """I encountered an error while validating the tool input. Here's what went wrong:
{{{exception}}}

Please help me understand what you're looking for more clearly, and I'll try again.""".strip()


USER_FILTER_OPTIONS_PROMPT = """
Goal: {{{change}}}

Current filters: {{{current_filters}}}

DO NOT CHANGE the fields that are not relevant to the change.
""".strip()
