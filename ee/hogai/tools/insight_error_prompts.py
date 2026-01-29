"""
Shared error prompts for insight creation tools.

These prompts are designed to prevent the AI from hallucinating
successful outcomes when insight creation fails (Bug #44592).
"""

INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT = """
<system_reminder>
CRITICAL: The insight was NOT created. No insight exists from this tool call.

You MUST:
1. Inform the user that the insight creation failed and explain the error.
2. Do NOT provide any insight names, IDs, or URLs - no insight was created.
3. Do NOT claim the insight exists or was saved - it was NOT.
4. Try to generate a new insight with a different query if appropriate.
5. Terminate if the error persists after multiple attempts.

NEVER fabricate, hallucinate, or make up insight names, IDs, short_ids, or URLs. The insight does not exist.
</system_reminder>
""".strip()

INSIGHT_TOOL_HANDLED_FAILURE_PROMPT = """
INSIGHT CREATION FAILED - NO INSIGHT WAS CREATED

The tool attempted to create an insight but encountered a validation error.
The insight was NOT saved and does NOT exist.

Generated output that failed validation:
```
{{{output}}}
```

Validation error:
```
{{{error_message}}}
```

{{{system_reminder}}}
""".strip()


INSIGHT_TOOL_UNHANDLED_FAILURE_PROMPT = """
INSIGHT CREATION FAILED - NO INSIGHT WAS CREATED

The tool encountered an unexpected error while creating an insight.
The insight was NOT saved and does NOT exist.

{{{system_reminder}}}
""".strip()
