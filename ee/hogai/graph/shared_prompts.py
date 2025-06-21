PROJECT_ORG_USER_CONTEXT_PROMPT = """
You are currently in project {{{project_name}}}, which is part of the {{{organization_name}}} organization.
The user's name is {{{user_full_name}}} ({{{user_email}}}). Feel free to refer by the first name when greeting them.
Current time in the project's timezone, {{{project_timezone}}}: {{{project_datetime}}}.
""".strip()
