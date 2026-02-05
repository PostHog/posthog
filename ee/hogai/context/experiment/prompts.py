EXPERIMENT_CONTEXT_TEMPLATE = """
## Experiment: {experiment_name}

**ID:** {experiment_id}
**Description:** {experiment_description}
**Feature Flag Key:** {feature_flag_key}
**Type:** {experiment_type}
**Status:** {experiment_status}
{dates_section}
{conclusion_section}
{variants_section}
{feature_flag_variants_section}
**Created:** {experiment_created_at}
""".strip()

EXPERIMENT_DATES_TEMPLATE = """
**Start Date:** {start_date}
**End Date:** {end_date}
""".strip()

EXPERIMENT_CONCLUSION_TEMPLATE = """
### Conclusion
**Result:** {conclusion}
{conclusion_comment_section}
""".strip()

EXPERIMENT_CONCLUSION_COMMENT_TEMPLATE = """
**Comment:** {conclusion_comment}
""".strip()

EXPERIMENT_VARIANTS_TEMPLATE = """
### Variants
{variants_list}
""".strip()

EXPERIMENT_FEATURE_FLAG_VARIANTS_TEMPLATE = """
### Feature Flag Variants
{variants_list}
""".strip()

EXPERIMENT_NOT_FOUND_TEMPLATE = """
Experiment with {identifier} was not found. Please verify the experiment ID or feature flag key is correct.
""".strip()
