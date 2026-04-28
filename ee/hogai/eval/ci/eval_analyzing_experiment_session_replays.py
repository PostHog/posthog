"""Evaluations for analyzing-experiment-session-replays skill."""

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

import pytest

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCallMessage, HumanMessage

from posthog.models import FeatureFlag

from products.experiments.backend.models.experiment import Experiment

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


# Mock recording metadata structure
class MockRecording(TypedDict):
    id: str
    distinct_id: str
    duration: int  # seconds
    start_time: str
    click_count: int
    keypress_count: int
    console_error_count: int
    first_url: str


# Mock analysis result structure
class MockAnalysisResult(TypedDict):
    variant_key: str
    recordings_count: int
    avg_duration: float
    avg_clicks: float
    error_rate: float
    behavioral_notes: list[str]


# Template for 2-variant Bayesian experiment
MOCK_TWO_VARIANT_EXPERIMENT: dict[str, Any] = {
    "name": "Checkout Flow Redesign",
    "description": "Testing simplified checkout vs current flow",
    "variants": ["control", "test"],
    "start_date_offset": -14,
    "end_date_offset": None,
    "recordings": {
        "control": [
            {
                "id": "rec_ctrl_1",
                "distinct_id": "user_1",
                "duration": 225,
                "start_time": "2026-04-20T10:30:00Z",
                "click_count": 18,
                "keypress_count": 42,
                "console_error_count": 2,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_ctrl_2",
                "distinct_id": "user_2",
                "duration": 198,
                "start_time": "2026-04-20T11:15:00Z",
                "click_count": 22,
                "keypress_count": 38,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_ctrl_3",
                "distinct_id": "user_5",
                "duration": 210,
                "start_time": "2026-04-20T14:30:00Z",
                "click_count": 20,
                "keypress_count": 40,
                "console_error_count": 2,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_ctrl_4",
                "distinct_id": "user_6",
                "duration": 235,
                "start_time": "2026-04-21T09:00:00Z",
                "click_count": 25,
                "keypress_count": 48,
                "console_error_count": 3,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_ctrl_5",
                "distinct_id": "user_7",
                "duration": 195,
                "start_time": "2026-04-21T15:45:00Z",
                "click_count": 19,
                "keypress_count": 36,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/checkout",
            },
        ],
        "test": [
            {
                "id": "rec_test_1",
                "distinct_id": "user_3",
                "duration": 150,
                "start_time": "2026-04-20T10:45:00Z",
                "click_count": 12,
                "keypress_count": 35,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_test_2",
                "distinct_id": "user_4",
                "duration": 142,
                "start_time": "2026-04-20T12:00:00Z",
                "click_count": 10,
                "keypress_count": 30,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_test_3",
                "distinct_id": "user_8",
                "duration": 155,
                "start_time": "2026-04-20T13:30:00Z",
                "click_count": 11,
                "keypress_count": 32,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_test_4",
                "distinct_id": "user_9",
                "duration": 165,
                "start_time": "2026-04-21T10:00:00Z",
                "click_count": 13,
                "keypress_count": 34,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/checkout",
            },
            {
                "id": "rec_test_5",
                "distinct_id": "user_10",
                "duration": 148,
                "start_time": "2026-04-21T16:20:00Z",
                "click_count": 11,
                "keypress_count": 33,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/checkout",
            },
        ],
    },
}

# Template for 3-variant experiment
MOCK_THREE_VARIANT_EXPERIMENT: dict[str, Any] = {
    "name": "Homepage Hero Test",
    "description": "Testing 3 different hero copy variations",
    "variants": ["control", "variant_a", "variant_b"],
    "start_date_offset": -21,
    "end_date_offset": -7,
    "recordings": {
        "control": [
            {
                "id": "rec_3v_ctrl_1",
                "distinct_id": "user_101",
                "duration": 180,
                "start_time": "2026-04-14T09:00:00Z",
                "click_count": 15,
                "keypress_count": 40,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_ctrl_2",
                "distinct_id": "user_102",
                "duration": 192,
                "start_time": "2026-04-14T14:30:00Z",
                "click_count": 17,
                "keypress_count": 42,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_ctrl_3",
                "distinct_id": "user_103",
                "duration": 165,
                "start_time": "2026-04-15T11:00:00Z",
                "click_count": 14,
                "keypress_count": 38,
                "console_error_count": 2,
                "first_url": "https://app.posthog.com/",
            },
        ],
        "variant_a": [
            {
                "id": "rec_3v_a_1",
                "distinct_id": "user_104",
                "duration": 140,
                "start_time": "2026-04-14T10:15:00Z",
                "click_count": 10,
                "keypress_count": 32,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_a_2",
                "distinct_id": "user_105",
                "duration": 155,
                "start_time": "2026-04-14T15:45:00Z",
                "click_count": 11,
                "keypress_count": 34,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_a_3",
                "distinct_id": "user_106",
                "duration": 148,
                "start_time": "2026-04-15T12:30:00Z",
                "click_count": 9,
                "keypress_count": 31,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/",
            },
        ],
        "variant_b": [
            {
                "id": "rec_3v_b_1",
                "distinct_id": "user_107",
                "duration": 170,
                "start_time": "2026-04-14T11:00:00Z",
                "click_count": 13,
                "keypress_count": 36,
                "console_error_count": 1,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_b_2",
                "distinct_id": "user_108",
                "duration": 185,
                "start_time": "2026-04-14T16:15:00Z",
                "click_count": 16,
                "keypress_count": 41,
                "console_error_count": 0,
                "first_url": "https://app.posthog.com/",
            },
            {
                "id": "rec_3v_b_3",
                "distinct_id": "user_109",
                "duration": 158,
                "start_time": "2026-04-15T13:45:00Z",
                "click_count": 12,
                "keypress_count": 37,
                "console_error_count": 2,
                "first_url": "https://app.posthog.com/",
            },
        ],
    },
}

# Template for draft experiment (should fail)
MOCK_DRAFT_EXPERIMENT: dict[str, Any] = {
    "name": "Unreleased Feature Test",
    "description": "Not yet launched",
    "variants": ["control", "test"],
    "start_date_offset": None,
    "end_date_offset": None,
    "recordings": {},
}

# Template for experiment with no recordings
MOCK_NO_RECORDINGS_EXPERIMENT: dict[str, Any] = {
    "name": "Low Traffic Test",
    "description": "Experiment with no session replay data",
    "variants": ["control", "test"],
    "start_date_offset": -7,
    "end_date_offset": None,
    "recordings": {
        "control": [],
        "test": [],
    },
}


@pytest.fixture
def experiment_with_feature_flag(
    demo_org_team_user,
) -> Callable[[dict[str, Any]], Awaitable[tuple[Experiment, FeatureFlag]]]:
    """Create experiment with feature flag matching mock template structure.

    Note: Does NOT create actual session replay records - those are mocked via monkeypatch in the test fixture.
    """
    _, team, user = demo_org_team_user

    async def setup(mock_template: dict[str, Any]) -> tuple[Experiment, FeatureFlag]:
        unique_suffix = uuid.uuid4().hex[:6]

        # Create feature flag with variants
        num_variants = len(mock_template["variants"])
        base_pct = 100 // num_variants
        remainder = 100 - (base_pct * num_variants)

        flag = await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=f"eval-session-replays-{unique_suffix}",
            name=f"{mock_template['name']} Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {
                            "key": variant,
                            "name": variant.title().replace("_", " "),
                            "rollout_percentage": base_pct + (remainder if i == 0 else 0),
                        }
                        for i, variant in enumerate(mock_template["variants"])
                    ]
                },
            },
        )

        # Create experiment
        now = datetime.now(tz=ZoneInfo("UTC"))
        start_date = (
            now + timedelta(days=mock_template["start_date_offset"])
            if mock_template["start_date_offset"] is not None
            else None
        )
        end_date = (
            now + timedelta(days=mock_template["end_date_offset"])
            if mock_template["end_date_offset"] is not None
            else None
        )

        experiment = await Experiment.objects.acreate(
            name=mock_template["name"],
            team=team,
            created_by=user,
            feature_flag=flag,
            description=mock_template["description"],
            start_date=start_date,
            end_date=end_date,
            metrics=[
                {
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "name": "Conversion",
                }
            ],
            metrics_secondary=[],
        )

        return experiment, flag

    return setup


def _extract_session_replay_analysis(state: AssistantState, mock_template: dict[str, Any] | None) -> dict[str, Any]:
    """Extract session replay analysis data from agent state.

    Returns:
        {
            "experiment_id": int | None,
            "feature_flag_key": str | None,
            "variants": list[str],
            "filters": dict[str, dict],  # variant_key -> filter_dict
            "recordings": dict[str, list],  # variant_key -> list of recordings
            "analysis": str | None,
            "steps_completed": list[str],
            "tool_calls": list[str],
            "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "experiment_id": None,
        "feature_flag_key": None,
        "variants": [],
        "filters": {},
        "recordings": {},
        "analysis": None,
        "steps_completed": set(),
        "tool_calls": [],
        "error": None,
    }

    # Extract from tool calls and results
    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_name = tool_call.name if hasattr(tool_call, "name") else str(tool_call)
                result["tool_calls"].append(tool_name)

                # Track workflow steps
                if "experiment" in tool_name.lower() or "execute_sql" in tool_name.lower():
                    result["steps_completed"].add("get_experiment_metadata")
                    # Try to extract experiment_id from args
                    if hasattr(tool_call, "args") and isinstance(tool_call.args, dict):
                        if "experiment_id" in tool_call.args:
                            result["experiment_id"] = tool_call.args["experiment_id"]

                if "feature_flag" in tool_name.lower():
                    result["steps_completed"].add("get_feature_flag_variants")
                    # Extract flag key from tool args
                    if hasattr(tool_call, "args") and isinstance(tool_call.args, dict):
                        if "flag_key" in tool_call.args:
                            result["feature_flag_key"] = tool_call.args["flag_key"]

                if "filter_session_recordings" in tool_name:
                    result["steps_completed"].add("retrieve_recordings")
                    # Extract filters from tool call args
                    if hasattr(tool_call, "args") and isinstance(tool_call.args, dict):
                        recordings_filters = tool_call.args.get("recordings_filters", {})
                        if recordings_filters:
                            # Try to determine which variant this filter is for
                            # by looking at the $feature/<flag_key> property filter
                            variant_key = None
                            if "filter_group" in recordings_filters:
                                filter_group = recordings_filters["filter_group"]
                                # Search for variant in nested filter structure
                                if isinstance(filter_group, dict) and "values" in filter_group:
                                    for val_group in filter_group.get("values", []):
                                        if isinstance(val_group, dict) and "values" in val_group:
                                            for filt in val_group.get("values", []):
                                                if isinstance(filt, dict) and filt.get("type") == "events":
                                                    for prop in filt.get("properties", []):
                                                        if isinstance(prop, dict):
                                                            key = prop.get("key", "")
                                                            if key.startswith("$feature/"):
                                                                value = prop.get("value", [])
                                                                if isinstance(value, list) and value:
                                                                    variant_key = value[0]
                                                                    break

                            # Store filter by variant
                            if variant_key:
                                result["filters"][variant_key] = recordings_filters
                                if variant_key not in result["variants"]:
                                    result["variants"].append(variant_key)
                            result["steps_completed"].add("build_filters")

        if isinstance(msg, AssistantToolCallMessage) and msg.content:
            # Parse tool results to extract recordings
            content = msg.content

            # Mocked tool returns formatted text with recording metadata
            # Associate result with the most recent filter variant
            if isinstance(content, str) and (
                "User:" in content or "Duration:" in content or "recording" in content.lower()
            ):
                # Find the most recent filter call that doesn't have recordings yet
                for variant in reversed(list(result["filters"].keys())):
                    if variant not in result["recordings"]:
                        result["recordings"][variant] = content
                        break

            # Check for errors (be more precise to avoid false positives)
            if isinstance(content, str):
                # Only match actual error indicators, not error metrics like "console_error_count: 0"
                import re

                error_patterns = [
                    r"\berror\b.*occurred",
                    r"\bfailed\b.*to",
                    r"exception",
                    r"cannot\b",
                    r"unable\b",
                    r"⚠️",  # Warning emoji from tool
                ]
                if any(re.search(pattern, content.lower()) for pattern in error_patterns):
                    result["error"] = content

    # Extract final analysis
    for msg in reversed(state.messages):
        if isinstance(msg, AssistantMessage) and msg.content and not msg.tool_calls:
            result["analysis"] = msg.content
            result["steps_completed"].add("analyze_and_compare")
            break

    # Ensure variants is populated from filters if not already set
    if not result["variants"] and result["filters"]:
        result["variants"] = list(result["filters"].keys())

    # If we have mock template, ensure variants match
    if mock_template and mock_template.get("variants"):
        if not result["variants"]:
            result["variants"] = mock_template["variants"]
        if not result["feature_flag_key"] and "name" in mock_template:
            # Extract from experiment name as fallback
            result["feature_flag_key"] = mock_template["name"].lower().replace(" ", "-")

    result["steps_completed"] = list(result["steps_completed"])

    return result


def _extract_variant_from_filter(recordings_filters: dict[str, Any], feature_flag_key: str) -> str | None:
    """Extract variant key from session recordings filter.

    Looks for $feature/<flag_key> property in the filter_group structure.
    """
    if "filter_group" not in recordings_filters:
        return None

    filter_group = recordings_filters["filter_group"]
    if not isinstance(filter_group, dict) or "values" not in filter_group:
        return None

    # Walk the nested structure: filter_group.values[].values[]
    for val_group in filter_group.get("values", []):
        if not isinstance(val_group, dict) or "values" not in val_group:
            continue

        for filt in val_group.get("values", []):
            if not isinstance(filt, dict):
                continue

            # Check if this is an events filter with properties
            if filt.get("type") == "events":
                for prop in filt.get("properties", []):
                    if not isinstance(prop, dict):
                        continue

                    key = prop.get("key", "")
                    # Match $feature/<flag_key>
                    if key == f"$feature/{feature_flag_key}":
                        value = prop.get("value", [])
                        if isinstance(value, list) and value:
                            return value[0]  # Return first variant in value list

    return None


def _format_mock_recording(recording: MockRecording) -> str:
    """Format mock recording metadata like the real tool."""
    parts = []

    # User/distinct_id
    distinct_id = recording.get("distinct_id", "Unknown")
    parts.append(f"User: {distinct_id}")

    # Start time
    start_time = recording.get("start_time")
    if start_time:
        from datetime import datetime

        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            parts.append(f"Started: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        except (ValueError, AttributeError):
            parts.append(f"Started: {start_time}")

    # Duration
    duration = recording.get("duration")
    if duration is not None:
        minutes = duration // 60
        seconds = duration % 60
        parts.append(f"Duration: {minutes}m {seconds}s")

    # Activity metrics
    click_count = recording.get("click_count")
    if click_count is not None:
        parts.append(f"Clicks: {click_count}")

    keypress_count = recording.get("keypress_count")
    if keypress_count is not None:
        parts.append(f"Keypresses: {keypress_count}")

    console_error_count = recording.get("console_error_count")
    if console_error_count is not None:
        parts.append(f"Console errors: {console_error_count}")

    # First URL
    first_url = recording.get("first_url")
    if first_url:
        parts.append(f"URL: {first_url}")

    return " | ".join(parts)


@pytest.fixture
def call_analyzing_session_replays_skill(
    demo_org_team_user, experiment_with_feature_flag, monkeypatch
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Execute the analyzing-experiment-session-replays skill and extract structured output."""
    _, team, user = demo_org_team_user

    async def execute(input: dict[str, Any]) -> dict[str, Any]:
        """Run skill graph and extract structured output from state.

        Args:
            input: Dictionary with:
                - "prompt": User's question/request with {experiment_id} placeholder
                - "mock_template": Optional mock data template for recordings (from MOCK_* constants)

        Returns:
            Dictionary with extracted structured data:
            {
                "experiment_id": int | None,
                "feature_flag_key": str | None,
                "variants": list[str],
                "filters": dict[str, Any],
                "recordings": dict[str, list],
                "analysis": str | None,
                "steps_completed": list[str],
                "tool_calls": list[str],
                "error": str | None
            }
        """
        user_prompt = input["prompt"]
        mock_template = input.get("mock_template")

        # Create experiment if mock_template provided
        if mock_template:
            experiment, feature_flag = await experiment_with_feature_flag(mock_template)
            # Substitute {experiment_id} placeholder
            user_input = user_prompt.format(experiment_id=experiment.id)

            # Mock the filter_session_recordings tool to return mock data
            async def mock_arun_impl(self, recordings_filters):
                """Return mock recordings based on variant in filter."""
                # Extract variant from filter
                variant_key = _extract_variant_from_filter(recordings_filters, feature_flag.key)

                # Get mock recordings for this variant
                mock_recordings = mock_template.get("recordings", {}).get(variant_key, [])

                # Format response like the real tool
                total_count = len(mock_recordings)
                if total_count == 0:
                    return "✅ Filtered session recordings. No recordings found matching these criteria.", None
                elif total_count == 1:
                    content = "✅ Filtered session recordings. Found 1 recording matching these criteria:\n\n"
                    content += _format_mock_recording(mock_recordings[0])
                    return content, None
                else:
                    content = (
                        f"✅ Filtered session recordings. Found {total_count} recordings matching these criteria:\n\n"
                    )
                    for i, recording in enumerate(mock_recordings[:5]):
                        content += f"{i + 1}. {_format_mock_recording(recording)}\n"
                    if total_count > 5:
                        content += f"\n...and {total_count - 5} more recordings"
                    return content, None

            # Patch the tool's _arun_impl method
            monkeypatch.setattr(
                "ee.hogai.tools.replay.filter_session_recordings.FilterSessionRecordingsTool._arun_impl",
                mock_arun_impl,
            )
        else:
            # No template, use prompt as-is (for invalid experiment ID tests)
            user_input = user_prompt

        # Create conversation
        conversation = await Conversation.objects.acreate(team=team, user=user)

        # Create graph with ROOT node for skill execution
        graph = (
            AssistantGraph(team, user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root()
            .compile(checkpointer=DjangoCheckpointer())
        )

        # Run graph with mocked tool (if template provided)
        state = await graph.ainvoke(
            AssistantState(messages=[HumanMessage(content=user_input)]),
            config=RunnableConfig(configurable={"thread_id": conversation.id}, recursion_limit=50),
        )

        # Extract structured output using dedicated function
        return _extract_session_replay_analysis(state, mock_template)

    return execute


class FilterConstructionCorrectness(Scorer):
    """Deterministic scorer validating session replay filter structure.

    Checks that the agent's output contains properly structured filters for each
    experiment variant with the required $feature_flag_called event and properties.

    Expected shape:
        {
            "variants": ["control", "test", ...]  # Required variant list
        }

    Output shape (from agent):
        {
            "filters": {
                "control": {
                    "events": [{"id": "$feature_flag_called", "properties": [...]}],
                    "date_from": "...",
                    ...
                },
                "test": {...},
                ...
            },
            "feature_flag_key": "...",
            "variants": ["control", "test", ...]
        }
    """

    def _name(self) -> str:
        return "filter_construction_correctness"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not isinstance(output, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output is not a dictionary"},
            )

        if not isinstance(expected, dict):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Expected variants not provided"},
            )

        variants = expected.get("variants", [])
        if not isinstance(variants, list) or not variants:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Expected variants must be a non-empty list"},
            )

        filters = output.get("filters")
        if not isinstance(filters, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output missing 'filters' dictionary"},
            )

        feature_flag_key = output.get("feature_flag_key")
        if not isinstance(feature_flag_key, str):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output missing 'feature_flag_key' string"},
            )

        output_variants = output.get("variants")
        if not isinstance(output_variants, list):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output missing 'variants' list"},
            )

        issues: list[str] = []
        variant_scores: list[float] = []

        expected_variant_prop = f"$feature/{feature_flag_key}"

        # Validate each variant has a proper filter
        for variant in variants:
            variant_filter = filters.get(variant)
            if not isinstance(variant_filter, dict):
                issues.append(f"Missing filter for variant '{variant}'")
                variant_scores.append(0.0)
                continue

            # Extract events from nested filter_group structure
            # Structure: filter_group.values[].values[] where type == "events"
            filter_group = variant_filter.get("filter_group")
            if not isinstance(filter_group, dict):
                issues.append(f"Variant '{variant}' missing filter_group")
                variant_scores.append(0.0)
                continue

            events_filters = []
            for val_group in filter_group.get("values", []):
                if isinstance(val_group, dict) and "values" in val_group:
                    for filt in val_group.get("values", []):
                        if isinstance(filt, dict) and filt.get("type") == "events":
                            events_filters.append(filt)

            if not events_filters:
                issues.append(f"Variant '{variant}' missing events filters in filter_group")
                variant_scores.append(0.0)
                continue

            # Check for $feature_flag_called event
            variant_errors: list[str] = []
            has_flag_called = False
            has_flag_property = False
            has_variant_property = False

            for event_filter in events_filters:
                if event_filter.get("id") == "$feature_flag_called":
                    has_flag_called = True
                    properties = event_filter.get("properties", [])
                    if isinstance(properties, list):
                        for prop in properties:
                            if not isinstance(prop, dict):
                                continue
                            prop_key = prop.get("key")
                            if prop_key == "$feature_flag":
                                has_flag_property = True
                                if feature_flag_key not in prop.get("value", []):
                                    variant_errors.append(f"{variant}: Incorrect $feature_flag value")
                            elif prop_key == expected_variant_prop:
                                has_variant_property = True
                                if variant not in prop.get("value", []):
                                    variant_errors.append(f"{variant}: Incorrect variant property value")

            if not has_flag_called:
                variant_errors.append(f"Variant '{variant}' missing $feature_flag_called event")
            if not has_flag_property:
                variant_errors.append(f"Variant '{variant}' missing $feature_flag property")
            if not has_variant_property:
                variant_errors.append(f"Variant '{variant}' missing $feature/{feature_flag_key} property")

            # Check date_from exists (at top level of variant_filter)
            if "date_from" not in variant_filter and "date_range" not in variant_filter:
                variant_errors.append(f"Variant '{variant}' missing date_from or date_range field")

            # Score this variant
            if variant_errors:
                issues.extend(variant_errors)
                variant_scores.append(0.0)
            else:
                variant_scores.append(1.0)

        avg_score = sum(variant_scores) / len(variant_scores) if variant_scores else 0.0

        if issues:
            return Score(
                name=self._name(),
                score=avg_score,
                metadata={"reason": "; ".join(issues), "errors": issues},
            )

        return Score(
            name=self._name(),
            score=1.0,
            metadata={"reason": "All filters correctly constructed"},
        )


class VariantExtractionCorrectness(Scorer):
    """Deterministic scorer validating variants were extracted from feature flag.

    Checks that the agent extracted variants from the feature flag's multivariate
    configuration, not from experiment.parameters. This validates the agent followed
    the correct data flow.

    Expected shape:
        {
            "variants": ["control", "test", ...]  # Required variant list
        }

    Output shape (from agent):
        {
            "queries_executed": ["system.feature_flags", ...],
            "tool_calls": ["feature_flag_get", ...],
            "variants": ["control", "test", ...],
            "variants_source": "feature_flag.filters.multivariate.variants"
        }
    """

    def _name(self) -> str:
        return "variant_extraction_correctness"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not isinstance(output, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output is not a dictionary"},
            )

        if not isinstance(expected, dict):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Expected variants not provided"},
            )

        expected_variants = expected.get("variants", [])
        if not isinstance(expected_variants, list) or not expected_variants:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Expected variants must be a non-empty list"},
            )

        output_variants = output.get("variants")
        if not isinstance(output_variants, list):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output missing 'variants' list"},
            )

        # Check if agent queried feature flag
        queries_executed = output.get("queries_executed", [])
        tool_calls = output.get("tool_calls", [])
        variants_source = output.get("variants_source", "")

        has_flag_query = False
        if isinstance(queries_executed, list):
            has_flag_query = any("feature_flag" in str(q).lower() for q in queries_executed)
        if not has_flag_query and isinstance(tool_calls, list):
            has_flag_query = any("feature_flag" in str(t).lower() for t in tool_calls)

        # Check variants source
        is_correct_source = False
        if isinstance(variants_source, str):
            is_correct_source = (
                "feature_flag" in variants_source.lower()
                and "multivariate" in variants_source.lower()
                and "experiment.parameters" not in variants_source.lower()
            )

        # Check if variants match
        variants_match = set(output_variants) == set(expected_variants)

        # Score logic:
        # 1.0 - Flag queried and variants match
        # 0.5 - Flag queried but variants don't match
        # 0.0 - No evidence of flag query
        if has_flag_query or is_correct_source:
            if variants_match:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={
                        "reason": "Variants correctly extracted from feature flag",
                        "source": variants_source,
                    },
                )
            else:
                return Score(
                    name=self._name(),
                    score=0.5,
                    metadata={
                        "reason": "Feature flag queried but variants don't match",
                        "expected": expected_variants,
                        "actual": output_variants,
                    },
                )
        else:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "No evidence of feature flag query; variants may be from experiment.parameters",
                    "queries": queries_executed,
                    "tool_calls": tool_calls,
                },
            )


class WorkflowCompletenessScorer(Scorer):
    """Deterministic scorer validating all 5 workflow steps were executed.

    Ensures the agent completed the entire analysis workflow in correct order:
    1. Get experiment metadata (experiment_id present in output)
    2. Get feature flag variants (queries include feature flag data)
    3. Build filters (filters dict present with variant-specific filters)
    4. Retrieve recordings (tool_calls include session_recording queries)
    5. Analyze and compare (analysis section present with variant comparisons)

    Output shape (inferred from agent's output):
        {
            "experiment_id": int,
            "queries_executed": [...],
            "filters": {...},
            "tool_calls": [...],
            "analysis": {...} or str
        }
    """

    REQUIRED_STEPS = {
        "get_experiment_metadata",
        "get_feature_flag_variants",
        "build_filters",
        "retrieve_recordings",
        "analyze_and_compare",
    }

    def _name(self) -> str:
        return "workflow_completeness"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output)

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not isinstance(output, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output is not a dictionary"},
            )

        # If steps_completed is explicitly provided, use it
        if "steps_completed" in output:
            steps_completed = set(output["steps_completed"])
            missing = self.REQUIRED_STEPS - steps_completed
            completion_rate = len(steps_completed & self.REQUIRED_STEPS) / len(self.REQUIRED_STEPS)

            return Score(
                name=self._name(),
                score=completion_rate,
                metadata={
                    "steps_completed": sorted(steps_completed & self.REQUIRED_STEPS),
                    "missing_steps": sorted(missing),
                    "completion_rate": f"{completion_rate:.1%}",
                },
            )

        # Otherwise, infer steps from output structure
        steps_completed = set()

        # Step 1: Get experiment metadata
        if "experiment_id" in output or "experiment" in output:
            steps_completed.add("get_experiment_metadata")

        # Step 2: Get feature flag variants
        queries_executed = output.get("queries_executed", [])
        tool_calls = output.get("tool_calls", [])
        if isinstance(queries_executed, list):
            if any("feature_flag" in str(q).lower() for q in queries_executed):
                steps_completed.add("get_feature_flag_variants")
        if isinstance(tool_calls, list):
            if any("feature_flag" in str(t).lower() for t in tool_calls):
                steps_completed.add("get_feature_flag_variants")

        # Step 3: Build filters
        filters = output.get("filters")
        if isinstance(filters, dict) and filters:
            steps_completed.add("build_filters")

        # Step 4: Retrieve recordings
        if isinstance(tool_calls, list):
            if any("session_recording" in str(t).lower() or "recording" in str(t).lower() for t in tool_calls):
                steps_completed.add("retrieve_recordings")

        # Step 5: Analyze and compare
        analysis = output.get("analysis")
        if analysis is not None and (isinstance(analysis, dict) or isinstance(analysis, str)):
            steps_completed.add("analyze_and_compare")

        missing = self.REQUIRED_STEPS - steps_completed
        completion_rate = len(steps_completed) / len(self.REQUIRED_STEPS)

        return Score(
            name=self._name(),
            score=completion_rate,
            metadata={
                "steps_completed": sorted(steps_completed),
                "missing_steps": sorted(missing),
                "completion_rate": f"{completion_rate:.1%}",
            },
        )


ANALYSIS_QUALITY_PROMPT = """
You are evaluating the quality of a session replay analysis comparing experiment variants.

The agent was given session recording metadata (duration, clicks, errors) for multiple variants
and asked to analyze behavioral differences. Your job is to assess the analysis quality.

Evaluate on these criteria:

1. Quantitative accuracy: Does the analysis correctly calculate and compare metrics?
   - Averages (duration, clicks, errors) should be accurate
   - Percentage differences should be correct
   - Comparisons should align with the data

2. Grounding: Are claims supported by the recording data provided?
   - No hallucinated patterns not present in the data
   - Specifics cited (e.g., "150s vs 225s") should match the recordings
   - Don't penalize reasonable interpretations of patterns

3. Qualitative insights: Does it go beyond raw numbers to interpret user behavior?
   - Explains what the metrics mean for UX
   - Identifies friction points or improvements
   - Connects metrics to user experience

4. Completeness: Does it cover all variants and key metrics?
   - All variants mentioned
   - Duration, interactions, errors addressed where relevant
   - Doesn't ignore obvious patterns in the data

5. Actionability: Does it provide a clear recommendation or next step?
   - Clear verdict (ship/don't ship/investigate further)
   - Reasoning tied to the analysis
   - Practical guidance for decision-making

Return:
- "PASS" if the analysis meets all criteria (quantitatively accurate, grounded, insightful, complete, actionable)
- "FAIL" if it fails on any major criterion (inaccurate numbers, hallucinated claims, missing variants, no recommendation)

Recording data:
{recordings}

Analysis to evaluate:
{analysis}
""".strip()


class AnalysisQualityScorer(LLMClassifier):
    """LLM-based scorer evaluating session replay analysis quality.

    Uses an LLM judge to assess whether the agent's analysis:
    - Accurately calculates metrics from recording data
    - Grounds claims in provided data (no hallucinations)
    - Provides qualitative behavioral insights beyond raw numbers
    - Covers all variants and key metrics
    - Delivers an actionable recommendation

    Output shape (from agent):
        {
            "recordings": {
                "control": [{"duration": 225, "clicks": 18, "errors": 2}, ...],
                "test": [{"duration": 150, "clicks": 12, "errors": 0}, ...]
            },
            "analysis": "The test variant shows significant improvements: ..."
        }
    """

    def __init__(self):
        super().__init__(
            name="analysis_quality",
            prompt_template=ANALYSIS_QUALITY_PROMPT,
            choice_scores={"PASS": 1.0, "FAIL": 0.0},
            model="gpt-4o",
            use_cot=True,
        )

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        """Synchronous evaluation wrapper."""
        if not isinstance(output, dict):
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Output is not a dictionary"},
            )

        recordings = output.get("recordings", {})
        analysis = output.get("analysis", "")

        if not analysis:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No analysis provided"},
            )

        # Format recordings for the prompt
        recordings_str = json.dumps(recordings, indent=2)

        # Call parent LLMClassifier with formatted inputs
        # The output is what gets evaluated, template vars are passed as kwargs
        return super()._run_eval_sync(
            output=analysis, expected=None, recordings=recordings_str, analysis=analysis, **kwargs
        )


class ErrorDetectionScorer(Scorer):
    """Validates that expected errors are properly caught and reported."""

    def _name(self) -> str:
        return "error_detection"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not expected or not expected.get("should_error"):
            return Score(name=self._name(), score=None, metadata={"reason": "Not an error case"})

        has_error = bool(output and output.get("error"))
        error_msg = output.get("error", "") if output else ""

        expected_msg_fragment = expected.get("error_message_contains", "")
        msg_matches = expected_msg_fragment.lower() in error_msg.lower() if error_msg else False

        if has_error and msg_matches:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"reason": "Error detected with expected message"},
            )
        elif has_error:
            return Score(
                name=self._name(),
                score=0.5,
                metadata={
                    "reason": "Error detected but message doesn't match",
                    "expected_fragment": expected_msg_fragment,
                    "actual_error": error_msg,
                },
            )
        else:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Expected error but none occurred"},
            )


@pytest.mark.skill_eval
@pytest.mark.django_db(databases=["default", "persons_db_writer"])
async def eval_analyzing_experiment_session_replays(
    call_analyzing_session_replays_skill,
    pytestconfig,
):
    """Evaluate the analyzing-experiment-session-replays skill."""
    from braintrust import EvalCase

    from ee.hogai.eval.base import MaxPublicEval

    await MaxPublicEval(
        experiment_name="analyzing_experiment_session_replays",
        task=call_analyzing_session_replays_skill,
        scores=[
            FilterConstructionCorrectness(),
            VariantExtractionCorrectness(),
            WorkflowCompletenessScorer(),
            AnalysisQualityScorer(),
            ErrorDetectionScorer(),
        ],
        data=[
            # Test case 1: Basic 2-variant experiment
            EvalCase(
                input={
                    "prompt": "How are users behaving in experiment {experiment_id}?",
                    "mock_template": MOCK_TWO_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "test"],
                    "analysis_should_mention": ["duration", "faster", "test"],
                },
                metadata={"test_type": "basic_2_variant"},
            ),
            # Test case 2: Multi-variant experiment
            EvalCase(
                input={
                    "prompt": "Compare session replays across all variants in experiment {experiment_id}",
                    "mock_template": MOCK_THREE_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "variant_a", "variant_b"],
                },
                metadata={"test_type": "multi_variant"},
            ),
            # Test case 3: Draft experiment (should error)
            EvalCase(
                input={
                    "prompt": "Show me session replays for experiment {experiment_id}",
                    "mock_template": MOCK_DRAFT_EXPERIMENT,
                },
                expected={
                    "should_error": True,
                    "error_message_contains": "draft",
                },
                metadata={"test_type": "draft_experiment"},
            ),
            # Test case 4: Experiment with no recordings
            EvalCase(
                input={
                    "prompt": "Analyze replays for experiment {experiment_id}",
                    "mock_template": MOCK_NO_RECORDINGS_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "test"],
                    "should_warn": True,
                    "warning_contains": "no recordings",
                },
                metadata={"test_type": "no_recordings"},
            ),
            # Test case 5: Date range filtering
            EvalCase(
                input={
                    "prompt": "Show session replays from the last 7 days of experiment {experiment_id}",
                    "mock_template": MOCK_TWO_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "test"],
                    "date_range": "last_7_days",
                },
                metadata={"test_type": "date_range"},
            ),
            # Test case 6: Single variant analysis
            EvalCase(
                input={
                    "prompt": "Show me only the test variant replays for experiment {experiment_id}",
                    "mock_template": MOCK_TWO_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants_analyzed": ["test"],
                },
                metadata={"test_type": "single_variant"},
            ),
            # Test case 7: Invalid experiment ID
            EvalCase(
                input={
                    "prompt": "Analyze session replays for experiment 99999",
                    "mock_template": None,
                },
                expected={
                    "should_error": True,
                    "error_message_contains": "not found",
                },
                metadata={"test_type": "invalid_experiment"},
            ),
            # Test case 8: Goal=decrease metric context (cart abandonment reduction)
            EvalCase(
                input={
                    "prompt": "How are users behaving in experiment {experiment_id}? This is testing cart abandonment reduction.",
                    "mock_template": {
                        "name": "Cart Abandonment Test",
                        "description": "Reduce cart abandonment rate",
                        "variants": ["control", "test"],
                        "start_date_offset": -7,
                        "end_date_offset": None,
                        "recordings": {
                            "control": [
                                {
                                    "id": "rec_c1",
                                    "distinct_id": "u1",
                                    "duration": 300,
                                    "start_time": "2026-04-21T10:00:00Z",
                                    "click_count": 25,
                                    "keypress_count": 50,
                                    "console_error_count": 3,
                                    "first_url": "https://app.posthog.com/cart",
                                },
                            ],
                            "test": [
                                {
                                    "id": "rec_t1",
                                    "distinct_id": "u2",
                                    "duration": 180,
                                    "start_time": "2026-04-21T10:30:00Z",
                                    "click_count": 15,
                                    "keypress_count": 30,
                                    "console_error_count": 0,
                                    "first_url": "https://app.posthog.com/cart",
                                },
                            ],
                        },
                    },
                },
                expected={
                    "variants": ["control", "test"],
                    "analysis_should_frame_reduction_as_positive": True,
                },
                metadata={"test_type": "goal_decrease"},
            ),
            # Test case 9: Multiple metrics context
            EvalCase(
                input={
                    "prompt": "Analyze replays for experiment {experiment_id}. We're tracking both conversion and revenue per user.",
                    "mock_template": MOCK_TWO_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "test"],
                },
                metadata={"test_type": "multiple_metrics"},
            ),
            # Test case 10: User experience friction analysis
            EvalCase(
                input={
                    "prompt": "What friction points are users experiencing in experiment {experiment_id}? Look for console errors and interaction patterns.",
                    "mock_template": MOCK_TWO_VARIANT_EXPERIMENT,
                },
                expected={
                    "variants": ["control", "test"],
                    "analysis_should_mention": ["errors", "clicks", "friction"],
                },
                metadata={"test_type": "friction_analysis"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
