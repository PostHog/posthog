FEATURE_FLAG_CONTEXT_TEMPLATE = """
## Feature Flag: {flag_key}

**ID:** {flag_id}
**Name/Description:** {flag_name}
**Active:** {flag_active}
**Created:** {flag_created_at}
{variants_section}
{release_conditions_section}
""".strip()

FEATURE_FLAG_VARIANTS_TEMPLATE = """
### Variants
{variants_list}
""".strip()

FEATURE_FLAG_RELEASE_CONDITIONS_TEMPLATE = """
### Release Conditions ({groups_count} group(s))
{conditions_list}
""".strip()

FEATURE_FLAG_NOT_FOUND_TEMPLATE = """
Feature flag with {identifier} was not found. Please verify the feature flag ID or key is correct.
""".strip()
