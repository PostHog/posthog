from typing import Any

from posthog.models.notebook.notebook import Notebook
from posthog.models.user import User
from posthog.models.team import Team
from ee.session_recordings.session_summary.patterns.output_data import EnrichedSessionGroupSummaryPatternsList


def create_summary_notebook(
    session_ids: list[str],
    user: User,
    team: Team,
    summary: EnrichedSessionGroupSummaryPatternsList,
    domain: str = "PostHog",
) -> Notebook:
    """Create a notebook with session summary patterns converted from EnrichedSessionGroupSummaryPatternsList"""
    notebook_content = _generate_notebook_content_from_summary(summary, session_ids, domain)
    notebook = Notebook.objects.create(
        team=team,
        title=f"Session Summaries Report - {domain}",
        content=notebook_content,
        created_by=user,
        last_modified_by=user,
    )

    return notebook


def _generate_notebook_content_from_summary(
    summary: EnrichedSessionGroupSummaryPatternsList, session_ids: list[str], domain: str
) -> dict[str, Any]:
    """Convert summary data to notebook content structure"""
    patterns = summary.patterns
    total_sessions = len(session_ids)

    if not patterns:
        return {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": f"Session Summaries Report - {domain}"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "No patterns found."}],
                },
            ],
        }

    # Sort patterns by severity: critical, high, medium, low
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns_sorted = sorted(
        patterns, key=lambda p: severity_order.get(p.severity.value if hasattr(p.severity, "value") else p.severity, 3)
    )

    content = []

    # Title
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": f"Session Summaries Report - {domain}"}],
        }
    )

    # Issues to review summary
    session_text = "session" if total_sessions == 1 else "sessions"
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": f"📊 Issues to review ({total_sessions} {session_text} scope)"}],
        }
    )

    # Summary table
    table_content = _create_summary_table(patterns_sorted, total_sessions)
    content.extend(table_content)

    # Pattern details
    for i, pattern in enumerate(patterns_sorted):
        pattern_content = _create_pattern_section(pattern, total_sessions, i == len(patterns_sorted) - 1)
        content.extend(pattern_content)

    return {
        "type": "doc",
        "content": content,
    }


def _create_summary_table(patterns: list, total_sessions: int) -> list[dict[str, Any]]:
    """Create summary table content"""
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

    table_content = []

    # Table header
    table_content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Pattern | Severity | Sessions | Failure Rate"}],
        }
    )
    table_content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "--------|----------|----------|-------------"}],
        }
    )

    # Table rows
    for pattern in patterns:
        stats = pattern.stats
        sessions_affected = stats.sessions_affected
        sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
        failure_percentage = f"{(1 - stats.segments_success_ratio) * 100:.0f}%"
        severity_icon = severity_icons.get(
            pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity, ""
        )

        severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity
        row_text = f"{pattern.pattern_name} | {severity_icon} {severity_text} | {sessions_percentage} ({sessions_affected}) | {failure_percentage}"
        table_content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": row_text}],
            }
        )

    return table_content


def _create_pattern_section(pattern, total_sessions: int, is_last: bool) -> list[dict[str, Any]]:
    """Create detailed pattern section content"""
    content = []

    # Pattern header
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": pattern.pattern_name}],
        }
    )

    # Pattern description
    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": pattern.pattern_description}],
        }
    )

    # Pattern stats
    stats = pattern.stats
    sessions_affected = stats.sessions_affected
    sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
    success_percentage = f"{stats.segments_success_ratio * 100:.0f}%"
    success_count = int(stats.segments_success_ratio * stats.occurences)

    severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity
    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": f"**How severe it is:** {severity_text.title()}"}],
        }
    )

    content.append(
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": f"**How many sessions affected:** {sessions_percentage} ({sessions_affected} out of {total_sessions})",
                }
            ],
        }
    )

    content.append(
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": f"**How often user succeeds, despite the pattern:** {success_percentage} ({success_count} out of {stats.occurences})",
                }
            ],
        }
    )

    # Detection indicators
    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "🔍 **How we detect this:**"}],
        }
    )

    for indicator in pattern.indicators:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"- {indicator}"}],
            }
        )

    # Examples section
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": "Examples"}],
        }
    )

    # Show up to 3 examples
    events_to_show = pattern.events[:3]
    total_events = len(pattern.events)

    for event_data in events_to_show:
        example_content = _create_example_section(event_data)
        content.extend(example_content)

    # Add note about remaining examples
    if total_events > 3:
        remaining_examples = total_events - 3
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "---"}],
            }
        )
        content.append(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": f"*📋 {len(events_to_show)} examples covered, you can research {remaining_examples} remaining examples at PostHog.com*",
                    }
                ],
            }
        )

    # Add spacing between patterns (except for the last one)
    if not is_last:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": ""}],
            }
        )
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "&nbsp;"}],
            }
        )

    return content


def _create_example_section(event_data) -> list[dict[str, Any]]:
    """Create example section content for an event"""
    content = []
    session_id = event_data.target_event.session_id

    # Example header
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 4},
            "content": [{"type": "text", "text": f"Session {session_id}"}],
        }
    )

    # Quick summary
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 5},
            "content": [{"type": "text", "text": "Quick summary"}],
        }
    )

    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": f"- **What user was doing:** {event_data.segment_name}"}],
        }
    )
    content.append(
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": f"- **What confirmed the pattern:** {event_data.target_event.description}"}
            ],
        }
    )
    content.append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": f"- **Where it happened:** {event_data.target_event.current_url}"}],
        }
    )

    # Outcome section
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 5},
            "content": [{"type": "text", "text": "Outcome"}],
        }
    )

    # What happened before
    if event_data.previous_events_in_segment:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "- **What happened before:**"}],
            }
        )
        for prev_event in event_data.previous_events_in_segment:
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": f"    - {prev_event.description}"}],
                }
            )
    else:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "- **What happened before:** Nothing, start of the segment"}],
            }
        )

    # What happened after
    if event_data.next_events_in_segment:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "- **What happened after:**"}],
            }
        )
        for next_event in event_data.next_events_in_segment:
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": f"    - {next_event.description}"}],
                }
            )
    else:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "- **What happened after:** Nothing, end of the segment"}],
            }
        )

    # Outcome
    outcome_status = "Success" if event_data.segment_success else "Failure"
    content.append(
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": f"- **What's the outcome:** {outcome_status}. {event_data.segment_outcome}"}
            ],
        }
    )

    return content
