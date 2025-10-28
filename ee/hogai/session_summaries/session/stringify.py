import json
from typing import Any

import structlog
from jinja2 import Template

logger = structlog.get_logger(__name__)

SESSION_STRING_FORMAT = """
# Session `{{ session_id }}`
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
- {%if issues_noticed%}Issues noticed: {{issues_noticed}}. {%endif%}{{ description }} at {{ relative_timestamp}}, as "{{ event }}"{%if event_type%} ({{ event_type }}){%endif%} event (event_uuid: `{{ event_uuid }}`).
"""


class SessionSummaryEventStringifier:
    def stringify_event(self, event: dict[str, Any]) -> str:
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
            segment_events.append(self.stringify_event(event))
        events_str = "".join(segment_events)
        outcome = self._find_segment_outcome(segment["index"])
        # Format the template
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

    def _find_session_id(self) -> str:
        for event in self.summary["key_actions"][0]["events"]:
            return event["session_id"]
        else:
            raise ValueError("Session ID not found in any of the key actions")


PATTERNS_STRING_FORMAT = """
# Patterns
{{ patterns_str }}
"""

PATTERN_STRING_FORMAT = """
## Pattern - {{ pattern_name }} ({{ severity }})
{{ pattern_description }}

### Potential indicators
{{ indicators_str }}

### Session examples
{{ examples_str }}
"""

EXAMPLE_SEGMENT_STRING_FORMAT = """
#### Session `{{ session_id }}` - Segment #{{ segment_index }}
{{ segment_name }}

**Key event:**{{ key_event_str }}

**Before it:**{{ previous_events_str }}

**After it:**{{ next_events_str }}

**Outcome:**
{%if segment_success%}Success{%else%}Failure{%endif%}. {{ segment_outcome }}.
"""

EXAMPLES_PER_PATTERN_LIMIT = 5


class SessionGroupSummaryStringifier(SessionSummaryEventStringifier):
    def __init__(self, summary: dict[str, Any], examples_per_pattern_limit: int = EXAMPLES_PER_PATTERN_LIMIT):
        self.summary = summary
        self.examples_per_pattern_limit = examples_per_pattern_limit

    def stringify_patterns(self) -> str:
        template = Template(PATTERNS_STRING_FORMAT)
        group_patterns = []
        for pattern in self.summary["patterns"]:
            group_patterns.append(self._stringify_pattern(pattern))
        patterns_str = "\n".join(group_patterns)
        context = {
            "patterns_str": patterns_str,
        }
        return self._clean_up(template.render(context))

    def _stringify_pattern(self, pattern: dict[str, Any]) -> str:
        template = Template(PATTERN_STRING_FORMAT)
        indicators_str = "\n".join([f"- {x}" for x in pattern["indicators"]])
        # Collect segment examples data
        pattern_segments = []
        # Limit examples for pattern, as Max don't need to see all them for meaningful context
        for segment in pattern["events"][: self.examples_per_pattern_limit]:
            pattern_segments.append(self._stringify_segment_example(segment))
        examples_str = "\n".join(pattern_segments)
        # Format the template
        context = {
            "pattern_name": pattern["pattern_name"],
            "severity": pattern["severity"],
            "pattern_description": pattern["pattern_description"],
            "indicators_str": indicators_str,
            "examples_str": examples_str,
        }
        return template.render(context)

    def _stringify_segment_example(self, segment: dict[str, Any]) -> str:
        template = Template(EXAMPLE_SEGMENT_STRING_FORMAT)
        session_id = self._find_session_id(segment)
        # Collect events data
        target_event_str = self.stringify_event(segment["target_event"])
        previous_events_str = "".join([self.stringify_event(event) for event in segment["previous_events_in_segment"]])
        if not previous_events_str:
            previous_events_str = "\n- Nothing, start of the segment."
        next_events_str = "".join([self.stringify_event(event) for event in segment["next_events_in_segment"]])
        if not next_events_str:
            next_events_str = "\n- Nothing, end of the segment."
        # Format the template
        context = {
            "session_id": session_id,
            "segment_index": segment["segment_index"],
            "segment_name": segment["segment_name"],
            "segment_success": segment["segment_success"],
            "segment_outcome": segment["segment_outcome"],
            "key_event_str": target_event_str,
            "previous_events_str": previous_events_str,
            "next_events_str": next_events_str,
        }
        return template.render(context)

    def _find_session_id(self, segment: dict[str, Any]) -> str:
        session_id = segment["target_event"].get("session_id")
        if not session_id:
            raise ValueError("Session ID not found in the segment target event")
        return session_id


# TODO: Remove after testing
if __name__ == "__main__":
    # Read the example single summary
    with open(
        "playground/identify-objectives-experiments/runs/592_2025-09-16_08-56-26/enriched_response_592_2025-09-16_08-56-26.yml",
    ) as f:
        example_summary_json = json.load(f)
    stringifier = SingleSessionSummaryStringifier(example_summary_json)
    session_str = stringifier.stringify_session()
    logger.info(session_str)

    # # Read the example session group summary
    # with open("/Users/woutut/Documents/Code/posthog/playground/patterns/patterns_extracted_example.json", "r") as f:
    #     example_summary_json = json.load(f)
    # stringifier = SessionGroupSummaryStringifier(example_summary_json)
    # session_str = stringifier.stringify_patterns()
    # logger.info(session_str)
