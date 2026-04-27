ERROR_TRACKING_ISSUE_CONTEXT_TEMPLATE = """\
## Error Tracking Issue: {issue_name}

**Issue ID:** {issue_id}
**Status:** {issue_status}
**Description:** {issue_description}

{noise_warning}### Event Context

{event_context}

### Stack Trace

{stacktrace}
{breadcrumbs_section}{replay_section}\
"""

THIRD_PARTY_NOISE_WARNING = (
    "**Likely third-party noise:** This issue is dominated by {noise_reason}. "
    "The captured stack trace is often unactionable for application owners — "
    "consider treating this as low-priority unless the trend correlates with a "
    "known release or change.\n\n"
)

REPLAY_SECTION_TEMPLATE = """
### Session Replay

A session recording was captured for this event (session_id: {session_id}). \
Session replays often show the user actions immediately preceding the error and \
may include console logs, network requests, and DOM changes that are not \
available from the stack trace alone.
"""

BREADCRUMBS_SECTION_TEMPLATE = """
### Breadcrumbs (most recent last)

{breadcrumbs}
"""
