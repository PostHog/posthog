FULL_TRACE_SUMMARY_PROMPT = """
- Analyze this conversation between the user and the PostHog AI assistant
- List all pain points, frustrations, and feature limitations the user experienced.
- IMPORTANT: Count only specific issues the user experienced when interacting with the assistant, don't guess or suggest.
- If no issues - return "No issues found" **without** any additional comments.
- If issues found - provide output as plain text in a maximum of 10 sentences, while highlighting all the crucial parts.
"""
