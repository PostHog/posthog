from datetime import datetime
import json
from typing import Any

from posthog.models.notebook.notebook import Notebook
from posthog.models.user import User
from posthog.models.team import Team
from ee.session_recordings.session_summary.patterns.output_data import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    PatternAssignedEventSegmentContext,
)

# Type aliases for TipTap editor nodes
TipTapNode = dict[str, Any]
TipTapContent = list[TipTapNode]


def create_summary_notebook(
    session_ids: list[str],
    user: User,
    team: Team,
    summary: EnrichedSessionGroupSummaryPatternsList,
    domain: str = "PostHog",
) -> Notebook:
    """Create a notebook with session summary patterns."""
    notebook_content = _generate_notebook_content_from_summary(summary, session_ids, domain)
    # TODO: Remove after testing
    with open("notebook_content.json", "w") as f:
        f.write(json.dumps(notebook_content, indent=4))
    notebook = Notebook.objects.create(
        team=team,
        title=f"Session Summaries Report - {domain} ({datetime.now().strftime('%Y-%m-%d')})",
        content=notebook_content,
        created_by=user,
        last_modified_by=user,
    )
    return notebook


def _generate_notebook_content_from_summary(
    summary: EnrichedSessionGroupSummaryPatternsList, session_ids: list[str], domain: str
) -> TipTapNode:
    """Convert summary data to notebook structure."""
    patterns = summary.patterns
    total_sessions = len(session_ids)
    if not patterns:
        return {
            "type": "doc",
            "content": [
                _create_heading_with_text(f"Session Summaries Report - {domain}", 1),
                _create_empty_paragraph(),
                _create_paragraph_with_text("No patterns found."),
            ],
        }

    # Sort patterns by severity: critical, high, medium, low
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns_sorted = sorted(
        patterns, key=lambda p: severity_order.get(p.severity.value if hasattr(p.severity, "value") else p.severity, 3)
    )
    content = []

    # Title
    content.append(_create_heading_with_text(f"Session Summaries Report - {domain}", 1))
    # Issues to review summary
    session_text = "session" if total_sessions == 1 else "sessions"
    content.append(_create_heading_with_text(f"📊 Issues to review ({total_sessions} {session_text} scope)", 2))
    # Summary table
    table_content = _create_summary_table(patterns_sorted, total_sessions)
    content.extend(table_content)
    content.append(_create_line_separator())

    # Pattern details
    for pattern in patterns_sorted:
        pattern_content = _create_pattern_section(pattern, total_sessions)
        content.append(_create_empty_paragraph())
        content.extend(pattern_content)

    return {
        "type": "doc",
        "content": content,
    }


def _sanitize_text_content(text: str) -> str:
    """Sanitize text content to ensure it's valid for TipTap editor."""
    if not text or not text.strip():
        raise ValueError(f"Empty text should not be passed to create heading or paragraph")
    return text.strip()


def _create_empty_paragraph() -> TipTapNode:
    """Create a paragraph node with no content to add spacing."""
    return {"type": "paragraph"}


def _create_line_separator() -> TipTapNode:
    """Create a line separator node."""
    return {"type": "horizontalRule"}


def _create_paragraph_with_text(text: str, marks: list[dict[str, Any]] | None = None) -> TipTapNode:
    """Create a paragraph node with sanitized text content and optional marks."""
    content_node: dict[str, Any] = {"type": "text", "text": _sanitize_text_content(text)}
    if marks:
        content_node["marks"] = marks
    return {
        "type": "paragraph",
        "content": [content_node],
    }


def _create_heading_with_text(text: str, level: int) -> TipTapNode:
    """Create a heading node with sanitized text content."""
    import uuid

    heading_id = str(uuid.uuid4())
    return {
        "type": "heading",
        "attrs": {"id": heading_id, "level": level, "data-toc-id": heading_id},
        "content": [{"type": "text", "text": _sanitize_text_content(text)}],
    }


def _create_text_content(text: str, is_bold: bool = False, is_italic: bool = False) -> TipTapNode:
    """Create a text node with optional marks."""
    node: dict[str, Any] = {"type": "text", "text": text}
    marks = []
    if is_bold:
        marks.append({"type": "bold"})
    if is_italic:
        marks.append({"type": "italic"})
    if marks:
        node["marks"] = marks
    return node


def _create_paragraph_with_content(content: TipTapContent) -> TipTapNode:
    """Create a paragraph node with a list of content items."""
    return {
        "type": "paragraph",
        "content": content,
    }


def _create_bullet_list(items: list[str] | list[TipTapContent] | TipTapContent) -> TipTapNode:
    """Create a bullet list with list items. Items can be strings or content arrays."""
    list_items = []
    for item in items:
        if isinstance(item, str):
            list_items.append({"type": "listItem", "content": [_create_paragraph_with_text(item)]})
        elif isinstance(item, list):
            # item is already a content array (could be paragraph + nested list)
            list_items.append({"type": "listItem", "content": item})
        else:
            # item is a single content node
            list_items.append({"type": "listItem", "content": [_create_paragraph_with_content([item])]})

    return {"type": "bulletList", "content": list_items}


def _create_summary_table(patterns: list[EnrichedSessionGroupSummaryPattern], total_sessions: int) -> TipTapContent:
    """Create summary table-like content using text formatting."""
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

    content = []

    # Create a table-like structure using bullet points
    table_items = []

    for pattern in patterns:
        stats = pattern.stats
        sessions_affected = stats.sessions_affected
        sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
        failure_percentage = f"{(1 - stats.segments_success_ratio) * 100:.0f}%"
        severity_icon = severity_icons.get(
            pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity, ""
        )
        severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity

        # Create a formatted item for each pattern
        pattern_info = [
            _create_text_content(f"{pattern.pattern_name} - ", is_bold=True),
            _create_text_content(f"{severity_icon} {severity_text} - "),
            _create_text_content(f"{sessions_percentage} ({sessions_affected}) sessions - "),
            _create_text_content(f"{failure_percentage} failure rate"),
        ]
        table_items.append(pattern_info)

    content.append(_create_bullet_list(table_items))

    return content


def _create_pattern_section(pattern: EnrichedSessionGroupSummaryPattern, total_sessions: int) -> TipTapContent:
    """Create detailed pattern section content."""
    content = []

    # Pattern header
    content.append(_create_heading_with_text(pattern.pattern_name, 2))
    # Pattern description
    content.append(_create_paragraph_with_text(pattern.pattern_description))

    # Pattern stats
    stats = pattern.stats
    sessions_affected = stats.sessions_affected
    sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
    success_percentage = f"{stats.segments_success_ratio * 100:.0f}%"
    success_count = int(stats.segments_success_ratio * stats.occurences)
    severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity
    content.append(_create_empty_paragraph())
    content.append(
        _create_paragraph_with_content(
            [_create_text_content("How severe it is: ", is_bold=True), _create_text_content(severity_text.title())]
        )
    )
    content.append(
        _create_paragraph_with_content(
            [
                _create_text_content("How many sessions affected: ", is_bold=True),
                _create_text_content(f"{sessions_percentage} ({sessions_affected} out of {total_sessions})"),
            ]
        )
    )
    content.append(
        _create_paragraph_with_content(
            [
                _create_text_content("How often users succeed, despite the pattern: ", is_bold=True),
                _create_text_content(f"{success_percentage} ({success_count} out of {stats.occurences})"),
            ]
        )
    )

    # Detection indicators
    content.append(_create_empty_paragraph())
    content.append(
        _create_paragraph_with_content(
            [_create_text_content("🔍 "), _create_text_content("How we detect this:", is_bold=True)]
        )
    )
    # Convert indicators to bullet list
    content.append(_create_bullet_list(pattern.indicators))

    # Examples section
    content.append(_create_empty_paragraph())
    content.append(_create_heading_with_text("Examples", 3))
    # TODO: Decide if to limit examples (or create some sort of collapsible section in notebooks)
    events_to_show = pattern.events
    for event_data in events_to_show:
        example_content = _create_example_section(event_data)
        content.append(_create_line_separator())
        content.extend(example_content)
    content.append(_create_line_separator())
    return content


def _create_example_section(event_data: PatternAssignedEventSegmentContext) -> TipTapContent:
    """Create example section content for an event."""
    content = []
    session_id = event_data.target_event.session_id
    # Calculate timestamp in seconds from milliseconds_since_start
    timestamp = int(event_data.target_event.milliseconds_since_start / 1000)

    # Example header with session link
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 4},
            "content": [
                {"type": "text", "text": "Session "},
                {
                    "type": "ph-backlink",
                    "attrs": {
                        "href": f"/project/1/replay/{session_id}?t={timestamp}",
                        "type": None,
                        "title": session_id,
                    },
                },
            ],
        }
    )
    # Quick summary
    content.append(_create_heading_with_text("Quick summary", 5))
    quick_summary_items = [
        [_create_text_content("What user was doing: ", is_bold=True), _create_text_content(event_data.segment_name)],
        [
            _create_text_content("What confirmed the pattern: ", is_bold=True),
            _create_text_content(event_data.target_event.description),
        ],
        [
            _create_text_content("Where it happened: ", is_bold=True),
            _create_text_content(event_data.target_event.current_url),
        ],
    ]
    content.append(_create_bullet_list(quick_summary_items))
    # Outcome section
    content.append(_create_heading_with_text("Outcome", 5))
    outcome_items = []
    # What happened before
    if event_data.previous_events_in_segment:
        # Add nested items for previous events
        prev_events_list = []
        for prev_event in event_data.previous_events_in_segment:
            prev_events_list.append(prev_event.description)

        # Create list item with paragraph and nested bullet list as content
        prev_events_content = [
            _create_paragraph_with_content([_create_text_content("What happened before:", is_bold=True)]),
            _create_bullet_list(prev_events_list),
        ]
        outcome_items.append(prev_events_content)
    else:
        outcome_items.append(
            [
                _create_text_content("What happened before: ", is_bold=True),
                _create_text_content("Nothing, start of the segment"),
            ]
        )

    # What happened after
    if event_data.next_events_in_segment:
        # Add nested items for next events
        next_events_list = []
        for next_event in event_data.next_events_in_segment:
            next_events_list.append(next_event.description)

        # Create list item with paragraph and nested bullet list as content
        next_events_content = [
            _create_paragraph_with_content([_create_text_content("What happened after:", is_bold=True)]),
            _create_bullet_list(next_events_list),
        ]
        outcome_items.append(next_events_content)
    else:
        outcome_items.append(
            [
                _create_text_content("What happened after: ", is_bold=True),
                _create_text_content("Nothing, end of the segment"),
            ]
        )

    # Outcome
    outcome_status = "Success" if event_data.segment_success else "Failure"
    outcome_items.append(
        [
            _create_text_content("What's the outcome: ", is_bold=True),
            _create_text_content(f"{outcome_status}. {event_data.segment_outcome}"),
        ]
    )

    content.append(_create_bullet_list(outcome_items))

    return content
