from typing import Any

import structlog
from jinja2 import Template

from ee.hogai.session_summaries.session.stringify import SessionSummaryEventStringifier

logger = structlog.get_logger(__name__)

EXAMPLES_PER_PATTERN_LIMIT = 5

PATTERNS_STRING_FORMAT = """# Patterns
{{ patterns_str }}"""

PATTERN_STRING_FORMAT = """
## Pattern: {{ pattern_name }} ({{ severity }})
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
        # Limit examples for pattern, as Intelligence doesn't need to see all them for meaningful context
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
