from datetime import datetime
from typing import TYPE_CHECKING

from posthog.models.notebook.notebook import Notebook
from posthog.models.notebook.util import (
    TipTapContent,
    TipTapNode,
    create_text_content,
    create_bullet_list,
    create_paragraph_with_content,
    create_paragraph_with_text,
    create_heading_with_text,
    create_task_list,
    create_empty_paragraph,
)
from posthog.models.user import User
from posthog.models.team import Team
from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    PatternAssignedEventSegmentContext,
    RawSessionGroupSummaryPattern,
)
from structlog import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    # TODO: Move enum to "types" and cleanup a bit to avoid circular imports
    from posthog.temporal.ai.session_summary.summarize_session_group import SessionSummaryStep


def format_single_sessions_status(sessions_status: dict[str, bool]) -> TipTapNode:
    """Format sessions status dictionary as a TipTap bullet list with a header"""
    items = []
    for session_id, is_completed in sessions_status.items():
        emoji = "✅" if is_completed else "❌"
        items.append(f"{session_id} {emoji}")

    bullet_list = create_bullet_list(items)
    # Add a proper header
    content = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Session Processing Status"}],
        },
        bullet_list,
    ]
    # Wrap content in a doc node
    json_content = {"type": "doc", "content": content}
    return json_content


def format_extracted_patterns_status(patterns: list[RawSessionGroupSummaryPattern]) -> TipTapNode:
    """Format extracted patterns as a TipTap document with header and details"""
    content = []
    # Add header
    content.append(
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Extracted Patterns"}]}
    )
    if not patterns:
        # Show a message when no patterns are extracted yet
        content.append(create_paragraph_with_text("No patterns extracted yet..."))
    else:
        # Create a list of patterns with their details
        pattern_items = []
        for pattern in patterns:
            # Create pattern header with name and severity
            pattern_name = pattern.pattern_name
            severity = pattern.severity
            pattern_header = f"**{pattern_name}** (Severity: {severity})"

            # Create pattern description
            pattern_desc = pattern.pattern_description

            # Create indicators list if available
            indicators = pattern.indicators
            if indicators:
                indicators_text = "Indicators: " + ", ".join(indicators)
                pattern_content = [
                    create_paragraph_with_text(pattern_header),
                    create_paragraph_with_text(pattern_desc),
                    create_paragraph_with_text(indicators_text),
                ]
            else:
                pattern_content = [create_paragraph_with_text(pattern_header), create_paragraph_with_text(pattern_desc)]

            # Add as a list item with nested content
            pattern_items.append({"type": "listItem", "content": pattern_content})

        # Add the bullet list
        content.append({"type": "bulletList", "content": pattern_items})

    return {"type": "doc", "content": content}


class NotebookIntermediateState:
    """Manages the intermediate state of a notebook during session group summarization."""

    def __init__(self, team_name: str):
        """Initialize the intermediate state with a plan."""
        from posthog.temporal.ai.session_summary.summarize_session_group import SessionSummaryStep

        self.team_name = team_name
        # Using dict to maintain order (Python 3.7+ guarantees order)
        self.plan_items: dict[SessionSummaryStep, tuple[str, bool]] = {
            SessionSummaryStep.WATCHING_SESSIONS: ("Watch sessions", False),
            SessionSummaryStep.FINDING_PATTERNS: ("Find patterns", False),
            SessionSummaryStep.GENERATING_REPORT: ("Generate final report", False),
        }
        # Store content for each step - allows late-arriving updates to be handled correctly
        self.steps_content: dict[SessionSummaryStep, TipTapNode] = {}
        self.current_step: SessionSummaryStep | None = SessionSummaryStep.WATCHING_SESSIONS

    @property
    def current_step_content(self) -> TipTapNode | None:
        """Get the content for the current step."""
        if self.current_step:
            return self.steps_content.get(self.current_step)
        return None

    @property
    def completed_steps(self) -> dict[str, TipTapNode]:
        """Get completed steps with their content."""
        completed = {}
        for step, (step_name, is_completed) in self.plan_items.items():
            if is_completed and step in self.steps_content:
                completed[step_name] = self.steps_content[step]
        return completed

    def update_step_progress(self, content: TipTapNode | None, step: "SessionSummaryStep") -> None:
        """Update the step's content and handle step transitions if needed."""
        # Update content for the specific step if provided
        if content:
            self.steps_content[step] = content

        # Only transition if moving forward to a new step
        if step != self.current_step and self._is_forward_transition(step):
            self._complete_and_transition(step)

    def _is_forward_transition(self, new_step: "SessionSummaryStep") -> bool:
        """Check if transitioning to new_step would be a forward transition."""
        if self.current_step is None:
            return True

        # Get the order of steps
        steps_list = list(self.plan_items.keys())
        try:
            current_index = steps_list.index(self.current_step)
            new_index = steps_list.index(new_step)
            return new_index > current_index
        except ValueError:
            # If step not found in plan, don't transition
            return False

    def _complete_and_transition(self, new_step: "SessionSummaryStep") -> None:
        """Complete current step and transition to the new step."""
        # If no current step - set the new step as current
        if self.current_step is None:
            self.current_step = new_step
            return

        # Mark current step as completed if it exists in plan
        if self.current_step in self.plan_items:
            step_name, _ = self.plan_items[self.current_step]
            self.plan_items[self.current_step] = (step_name, True)

        # Update current step
        self.current_step = new_step

    def format_intermediate_state(self) -> TipTapNode:
        """Convert the intermediate state to TipTap format for display."""
        content = []

        # Add main title
        content.append(create_heading_with_text(f"Session Group Analysis - {self.team_name}", 1))
        content.append(create_empty_paragraph())

        # Add plan section
        content.append(create_heading_with_text("Plan", 2))
        # Extract just the name and completion status for the task list
        task_list_items = [(name, completed) for name, completed in self.plan_items.values()]
        content.append(create_task_list(task_list_items))

        # Add current step content if exists
        if self.current_step_content:
            content.append(create_empty_paragraph())
            # Extract content from the doc node if it's wrapped
            # TODO: Do I need the check of I can guarantee `doc` every time?
            if isinstance(self.current_step_content, dict) and self.current_step_content.get("type") == "doc":
                content.extend(self.current_step_content.get("content", []))
            else:
                content.append(self.current_step_content)

        # Add completed steps in reverse order (most recent first)
        for step_name, step_content in reversed(list(self.completed_steps.items())):
            content.append(create_empty_paragraph())
            content.append(_create_line_separator())
            content.append(create_heading_with_text(f"Step: {step_name} (Completed)", 2))
            # Extract content from the doc node if it's wrapped
            # TODO: Do I need the check of I can guarantee `doc` every time?
            if isinstance(step_content, dict) and step_content.get("type") == "doc":
                content.extend(step_content.get("content", []))
            else:
                content.append(step_content)

        return {"type": "doc", "content": content}


async def create_empty_notebook_for_summary(user: User, team: Team) -> Notebook:
    """Create an empty notebook for a summary."""
    notebook = await Notebook.objects.acreate(
        team=team,
        title=f"Session Summaries Report - {team.name} ({datetime.now().strftime('%Y-%m-%d')})",
        content="",
        created_by=user,
        last_modified_by=user,
    )
    return notebook


async def create_notebook_from_summary_content(
    session_ids: list[str], user: User, team: Team, summary_content: TipTapNode
) -> Notebook:
    """Create a notebook with session summary patterns."""
    notebook = await Notebook.objects.acreate(
        team=team,
        title=f"Session Summaries Report - {team.name} ({datetime.now().strftime('%Y-%m-%d')})",
        content=summary_content,
        created_by=user,
        last_modified_by=user,
    )
    return notebook


# async def update_notebook_with_summary(
#     notebook_short_id: str,
#     session_ids: list[str],
#     team: Team,
#     summary: EnrichedSessionGroupSummaryPatternsList,
# ) -> Notebook:
#     """Update a notebook with session summary patterns."""
#     notebook = await Notebook.objects.aget(short_id=notebook_short_id)
#     notebook_content = _generate_notebook_content_from_summary(
#         summary=summary, session_ids=session_ids, project_name=team.name, team_id=team.id
#     )
#     notebook.content = notebook_content
#     await notebook.asave()
#     return notebook


def generate_notebook_content_from_summary(
    summary: EnrichedSessionGroupSummaryPatternsList, session_ids: list[str], project_name: str, team_id: int
) -> TipTapNode:
    """Convert summary data to notebook structure."""
    patterns = summary.patterns
    total_sessions = len(session_ids)
    if not patterns:
        return {
            "type": "doc",
            "content": [
                create_heading_with_text(f"Session Summaries Report - {project_name}", 1),
                create_empty_paragraph(),
                create_paragraph_with_text("No patterns found."),
                create_paragraph_with_text(f"Sessions covered: {', '.join(session_ids)}"),
            ],
        }

    # Sort patterns by severity: critical, high, medium, low
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns_sorted = sorted(
        patterns, key=lambda p: severity_order.get(p.severity.value if hasattr(p.severity, "value") else p.severity, 3)
    )
    content = []

    # Title
    content.append(create_heading_with_text(f"Session Summaries Report - {project_name}", 1))
    # Issues to review summary
    session_text = "session" if total_sessions == 1 else "sessions"
    content.append(create_heading_with_text(f"📊 Issues to review ({total_sessions} {session_text} scope)", 2))
    # Summary table
    table_content = _create_summary_table(patterns_sorted, total_sessions)
    content.extend(table_content)
    content.append(_create_line_separator())

    # Pattern details
    for pattern in patterns_sorted:
        pattern_content = _create_pattern_section(pattern=pattern, total_sessions=total_sessions, team_id=team_id)
        content.append(create_empty_paragraph())
        content.extend(pattern_content)

    content.extend(
        [
            create_empty_paragraph(),
            _create_line_separator(),
            create_paragraph_with_text(f"Sessions covered: {', '.join(session_ids)}"),
        ]
    )

    return {
        "type": "doc",
        "content": content,
    }


def _milliseconds_to_timestamp(milliseconds: int) -> str:
    """Convert milliseconds to HH:MM:SS format."""
    seconds = milliseconds // 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _create_line_separator() -> TipTapNode:
    """Create a line separator node."""
    return {"type": "horizontalRule"}


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
            create_text_content(f"{pattern.pattern_name} - ", is_bold=True),
            create_text_content(f"{severity_icon} {severity_text} - "),
            create_text_content(f"{sessions_percentage} ({sessions_affected}) sessions - "),
            create_text_content(f"{failure_percentage} failure rate"),
        ]
        table_items.append(pattern_info)

    content.append(create_bullet_list(table_items))

    return content


def _create_pattern_section(
    pattern: EnrichedSessionGroupSummaryPattern, total_sessions: int, team_id: int
) -> TipTapContent:
    """Create detailed pattern section content."""
    content = []

    # Pattern header
    content.append(create_heading_with_text(pattern.pattern_name, 2))
    # Pattern description
    content.append(create_paragraph_with_text(pattern.pattern_description))

    # Pattern stats
    stats = pattern.stats
    sessions_affected = stats.sessions_affected
    sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
    success_percentage = f"{stats.segments_success_ratio * 100:.0f}%"
    success_count = int(stats.segments_success_ratio * stats.occurences)
    severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity
    content.append(create_empty_paragraph())
    content.append(
        create_paragraph_with_content(
            [create_text_content("How severe it is: ", is_bold=True), create_text_content(severity_text.title())]
        )
    )
    content.append(
        create_paragraph_with_content(
            [
                create_text_content("How many sessions affected: ", is_bold=True),
                create_text_content(f"{sessions_percentage} ({sessions_affected} out of {total_sessions})"),
            ]
        )
    )
    content.append(
        create_paragraph_with_content(
            [
                create_text_content("How often users succeed, despite the pattern: ", is_bold=True),
                create_text_content(f"{success_percentage} ({success_count} out of {stats.occurences})"),
            ]
        )
    )

    # Detection indicators
    content.append(create_empty_paragraph())
    content.append(
        create_paragraph_with_content(
            [create_text_content("🔍 "), create_text_content("How we detect this:", is_bold=True)]
        )
    )
    # Convert indicators to bullet list
    content.append(create_bullet_list(pattern.indicators))

    # Examples section
    content.append(create_empty_paragraph())
    content.append(create_heading_with_text("Examples", 3))
    # TODO: Decide if to limit examples (or create some sort of collapsible section in notebooks)
    events_to_show = pattern.events
    for event_data in events_to_show:
        example_content = _create_example_section(event_data=event_data, team_id=team_id)
        content.append(_create_line_separator())
        content.extend(example_content)
    content.append(_create_line_separator())
    return content


def _create_example_section(event_data: PatternAssignedEventSegmentContext, team_id: int) -> TipTapContent:
    """Create example section content for an event."""
    content = []
    session_id = event_data.target_event.session_id
    # Calculate seconds till start, so link opens player on a proper position
    seconds_since_start = int(event_data.target_event.milliseconds_since_start / 1000)

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
                        "href": f"/project/{team_id}/replay/{session_id}?t={seconds_since_start}",
                        "type": None,
                        "title": session_id,
                    },
                },
                {
                    "type": "text",
                    "text": f" at {_milliseconds_to_timestamp(event_data.target_event.milliseconds_since_start)}",
                },
            ],
        }
    )
    # Quick summary
    content.append(create_heading_with_text("Quick summary", 5))
    quick_summary_items = [
        [create_text_content("What user was doing: ", is_bold=True), create_text_content(event_data.segment_name)],
        [
            create_text_content("What confirmed the pattern: ", is_bold=True),
            create_text_content(event_data.target_event.description),
        ],
        [
            create_text_content("Where it happened: ", is_bold=True),
            create_text_content(event_data.target_event.current_url),
        ],
    ]
    content.append(create_bullet_list(quick_summary_items))
    # Outcome section
    content.append(create_heading_with_text("Outcome", 5))
    outcome_items = []
    # What happened before
    if event_data.previous_events_in_segment:
        # Add nested items for previous events
        prev_events_list = []
        for prev_event in event_data.previous_events_in_segment:
            prev_events_list.append(prev_event.description)

        # Create list item with paragraph and nested bullet list as content
        prev_events_content = [
            create_paragraph_with_content([create_text_content("What happened before:", is_bold=True)]),
            create_bullet_list(prev_events_list),
        ]
        outcome_items.append(prev_events_content)
    else:
        outcome_items.append(
            [
                create_text_content("What happened before: ", is_bold=True),
                create_text_content("Nothing, start of the segment"),
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
            create_paragraph_with_content([create_text_content("What happened after:", is_bold=True)]),
            create_bullet_list(next_events_list),
        ]
        outcome_items.append(next_events_content)
    else:
        outcome_items.append(
            [
                create_text_content("What happened after: ", is_bold=True),
                create_text_content("Nothing, end of the segment"),
            ]
        )

    # Outcome
    outcome_status = "Success" if event_data.segment_success else "Failure"
    outcome_items.append(
        [
            create_text_content("What's the outcome: ", is_bold=True),
            create_text_content(f"{outcome_status}. {event_data.segment_outcome}"),
        ]
    )

    content.append(create_bullet_list(outcome_items))

    return content
