ACCOUNT_CONTEXT_TEMPLATE = """
## Account: {name}

**ID:** {account_id}
**External ID:** {external_id}
**Created:** {created_at}
{roles_section}
{external_ids_section}
{tags_section}
{notes_section}

{analysis_section}
""".strip()

ACCOUNT_ROLES_TEMPLATE = """
### Roles
{roles_list}
""".strip()

ACCOUNT_EXTERNAL_IDS_TEMPLATE = """
### External-system ids
{ids_list}
""".strip()

ACCOUNT_TAGS_TEMPLATE = """
### Tags
{tags_list}
""".strip()

ACCOUNT_NOTES_TEMPLATE = """
### Saved notes
{notes_list}
""".strip()

# The analysis section carries the account→group link so it lands in conversation history
# before a switch_mode (which forwards only history). It is fenced and labelled internal so the
# agent uses it to scope analysis without surfacing the raw identifiers to the user.
ACCOUNT_ANALYSIS_CONNECTED_TEMPLATE = """
<account_analysis_context>
For your own analysis only — do not repeat these identifiers to the user.
This account is connected to its product data as group type index {group_type_index}, group key "{group_key}".
To answer questions about its usage, events, or feature flags, switch to product analytics or SQL and scope the analysis to this group. Its usage trends also live in the account's Usage tab in the Accounts list.
</account_analysis_context>
""".strip()

ACCOUNT_ANALYSIS_NO_EXTERNAL_ID_TEMPLATE = """
<account_analysis_context>
This account has no external ID, so it isn't linked to its product data and usage or event questions can't be answered yet. Ask the user to set the account's external ID to the organization's key in product data so it can be connected.
</account_analysis_context>
""".strip()

ACCOUNT_ANALYSIS_NOT_CONFIGURED_TEMPLATE = """
<account_analysis_context>
Customer analytics isn't connected to a group type for this project yet, so this account's usage and event data can't be analyzed. Ask the user to finish setup in Customer analytics > Accounts settings.
</account_analysis_context>
""".strip()

ACCOUNT_ANALYSIS_GROUP_NOT_FOUND_TEMPLATE = """
<account_analysis_context>
This account's external ID "{group_key}" doesn't match any known group in product data, so its usage and event data may be unavailable. Verify the external ID matches the organization's key in product data.
</account_analysis_context>
""".strip()

ACCOUNT_NOT_FOUND_TEMPLATE = """
Account with {identifier} was not found. Verify the account id or external id is correct, or use list_data with the account kind to find it.
""".strip()
