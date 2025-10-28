import json
from typing import Any

import structlog
from jinja2 import Template

logger = structlog.get_logger(__name__)

SESSION_STRING_FORMAT = """
# Session {{ session_id }}
{%if success%}Success{%else%}Failure{%endif%}. {{ description }}.
{{ session_segments_str }}
"""


SEGMENT_STRING_FORMAT = """
## Segment #{{ segment_index }}
{{ segment_name }}. User spent {{ relative_timestamp }}, performing {{ segment_events_count }} events.

### What the user did {{ events_str }}

### Segment outcome
{%if success%}Success{%else%}Failure{%endif%}. {{ summary }}.
"""

EVENT_STRING_FORMAT = """
- {%if issues_noticed%}Issues noticed: {{issues_noticed}}. {%endif%}{{ description }} at {{ relative_timestamp}}, as "{{ event }}"{%if event_type%} ({{ event_type }}){%endif%} event (event_uuid: {{ event_uuid }}).
"""


class SingleSessionSummaryStringifier:
    def __init__(self, summary: dict[str, Any]):
        self.summary = summary
        self.session_id: str | None = None  # Fill when iterating over events

    def stringify_session(self) -> str:
        template = Template(SESSION_STRING_FORMAT)
        # Collect segments data
        session_segments = []
        for segment in self.summary["segments"]:
            session_segments.append(self._stringify_segment(segment))
        session_segments_str = "\n".join(session_segments)
        # Collect session outcome data
        session_outcome = self.summary["session_outcome"]
        context = {
            "session_id": self.session_id,
            "success": session_outcome["success"],
            "description": session_outcome["description"],
            "session_segments_str": session_segments_str,
        }
        return template.render(context)

    def _find_segment_key_actions_events(self, segment_id: int) -> list[dict[str, Any]]:
        for key_actions in self.summary["key_actions"]:
            if key_actions["segment_index"] == segment_id:
                return key_actions["events"]
        else:
            # Each segment should have at least one key action
            raise ValueError(f"Segment key actions not found for segment_id {segment_id}")

    def _find_segment_outcome(self, segment_id: int) -> dict[str, Any]:
        for outcome in self.summary["segment_outcomes"]:
            if outcome["segment_index"] == segment_id:
                return outcome
        else:
            # Each segment should have at least one outcome
            raise ValueError(f"Segment outcome not found for segment_id {segment_id}")

    def _stringify_segment(self, segment: dict[str, Any]) -> str:
        template = Template(SEGMENT_STRING_FORMAT)
        # Collect key actions data
        segment_events = []
        key_actions_events = self._find_segment_key_actions_events(segment["index"])
        for event in key_actions_events:
            segment_events.append(self._stringify_event(event))
            if not self.session_id:
                self.session_id = event["session_id"]
        events_str = "".join(segment_events)
        # Collect outcome data
        outcome = self._find_segment_outcome(segment["index"])
        summary, success = outcome["summary"], outcome["success"]
        context = {
            "segment_index": segment["index"],
            "segment_name": segment["name"],
            "relative_timestamp": self._ms_to_hh_mm_ss(segment["meta"]["duration"]),
            "segment_events_count": segment["meta"]["events_count"],
            "events_str": events_str,
            "success": success,
            "summary": summary,
        }
        return template.render(context)

    def _stringify_event(self, event: dict[str, Any]) -> str:
        template = Template(EVENT_STRING_FORMAT)
        issues_noticed = []
        for issue in ["abandonment", "confusion", "exception"]:
            if event[issue]:
                issues_noticed.append(issue)
        context = {
            "issues_noticed": ", ".join(issues_noticed),
            "description": event["description"],
            "relative_timestamp": self._ms_to_hh_mm_ss(event["milliseconds_since_start"]),
            "event": event["event"],
            "event_type": event["event_type"],
            "event_uuid": event["event_uuid"],
        }
        event_str = template.render(context)
        return event_str

    @staticmethod
    def _ms_to_hh_mm_ss(ms: int) -> str:
        seconds = ms // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# TODO: Remove after testing
if __name__ == "__main__":
    # Read the example summary
    with open(
        "playground/identify-objectives-experiments/runs/592_2025-09-16_08-56-26/enriched_response_592_2025-09-16_08-56-26.yml",
    ) as f:
        example_summary_json = json.load(f)
    stringifier = SingleSessionSummaryStringifier(example_summary_json)
    session_str = stringifier.stringify_session()
    logger.info(session_str)
