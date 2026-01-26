SURVEY_CONTEXT_TEMPLATE = """
## Survey: {survey_name}

**Survey ID:** {survey_id}
**Type:** {survey_type}
**Status:** {survey_status}
**Description:** {survey_description}

### Questions

{questions}

### Targeting Configuration

{targeting}

### Response Summary

{response_summary}
""".strip()
