from typing import Any

import structlog
from jinja2 import Template

logger = structlog.get_logger(__name__)

SESSION_STRING_FORMAT = """# Session `{{ session_id }}`
{%if success%}Success{%else%}Failure{%endif%}. {{ description }}.
{{ session_segments_str }}"""

SEGMENT_STRING_FORMAT = """
## Segment #{{ segment_index }}
{{ segment_name }}. User spent {{ duration }}s, performing {{ segment_events_count }} events.

### What the user did {{ events_str }}

### Segment outcome
{%if success%}Success{%else%}Failure{%endif%}. {{ summary }}.
"""

EVENT_STRING_FORMAT = """
- {%if issues_noticed%}Issues noticed: {{issues_noticed}}. {%endif%}{{ description }} at {{ relative_timestamp}}, as "{{ event }}"{%if event_type%} ({{ event_type }}){%endif%} event (event_uuid: `{{ event_uuid }}`).
"""


class SessionSummaryEventStringifier:
    def stringify_event(self, event: dict[str, Any]) -> str:
        template = Template(EVENT_STRING_FORMAT)
        issues_noticed = []
        for issue in ["abandonment", "confusion", "exception"]:
            if event[issue]:
                if issue == "exception":
                    issue = f'{event["exception"]} exception'
                issues_noticed.append(issue)
        context = {
            "issues_noticed": ", ".join(issues_noticed),
            "description": event["description"],
            "relative_timestamp": self._ms_to_hh_mm_ss(event["milliseconds_since_start"]),
            "event": event["event"],
            "event_type": event["event_type"],
            "event_uuid": event["event_uuid"],
        }
        return self._clean_up(template.render(context))

    @staticmethod
    def _ms_to_hh_mm_ss(ms: int) -> str:
        seconds = ms // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _clean_up(part_str: str) -> str:
        # Basic cleanup to cover most incorrect formatting cases
        return part_str.replace("  ", " ").replace("..", ".")


class SingleSessionSummaryStringifier(SessionSummaryEventStringifier):
    def __init__(self, summary: dict[str, Any]):
        self.summary = summary

    def stringify_session(self) -> str:
        template = Template(SESSION_STRING_FORMAT)
        # Collect segments data
        session_segments = []
        for segment in self.summary["segments"]:
            session_segments.append(self._stringify_segment(segment))
        session_segments_str = "\n".join(session_segments)
        session_outcome = self.summary["session_outcome"]
        session_id = self._find_session_id()
        # Format the template
        context = {
            "session_id": session_id,
            "success": session_outcome["success"],
            "description": session_outcome["description"],
            "session_segments_str": session_segments_str,
        }
        return self._clean_up(template.render(context))

    def _find_segment_key_actions_events(self, segment_id: int) -> list[dict[str, Any]]:
        for key_actions in self.summary["key_actions"]:
            if key_actions["segment_index"] == segment_id:
                return key_actions["events"]
        # Each segment should have at least one key action
        raise ValueError(f"Segment key actions not found for segment_id {segment_id}")

    def _find_segment_outcome(self, segment_id: int) -> dict[str, Any]:
        for outcome in self.summary["segment_outcomes"]:
            if outcome["segment_index"] == segment_id:
                return outcome
        # Each segment should have at least one outcome
        raise ValueError(f"Segment outcome not found for segment_id {segment_id}")

    def _stringify_segment(self, segment: dict[str, Any]) -> str:
        template = Template(SEGMENT_STRING_FORMAT)
        # Collect key actions data
        segment_events = []
        key_actions_events = self._find_segment_key_actions_events(segment["index"])
        for event in key_actions_events:
            segment_events.append(self.stringify_event(event))
        events_str = "".join(segment_events)
        outcome = self._find_segment_outcome(segment["index"])
        # Format the template
        summary, success = outcome["summary"], outcome["success"]
        context = {
            "segment_index": segment["index"],
            "segment_name": segment["name"],
            "duration": segment["meta"]["duration"],
            "segment_events_count": segment["meta"]["events_count"],
            "events_str": events_str,
            "success": success,
            "summary": summary,
        }
        return template.render(context)

    def _find_session_id(self) -> str:
        if self.summary["key_actions"] and self.summary["key_actions"][0]["events"]:
            return self.summary["key_actions"][0]["events"][0]["session_id"]
        raise ValueError("Session ID not found in the first key action")
