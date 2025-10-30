import copy
import json
import uuid
from dataclasses import asdict, dataclass
from math import floor
from pathlib import Path
from typing import Any, cast

import yaml
import structlog
from glom import (
    PathAccessError,
    assign as assign_value,
    glom as find_value,
)

from posthog.models.user import User

from ee.hogai.session_summaries.constants import (
    EXPIRES_AFTER_DAYS,
    FAILED_MOMENTS_MIN_RATIO,
    SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO,
    VALIDATION_VIDEO_DURATION,
)
from ee.hogai.session_summaries.llm.call import call_llm
from ee.hogai.session_summaries.llm.consume import get_raw_content
from ee.hogai.session_summaries.session.output_data import (
    EnrichedKeyActionSerializer,
    IntermediateSessionSummarySerializer,
    SessionSummaryExceptionTypes,
    SessionSummaryIssueTypes,
    SessionSummarySerializer,
)
from ee.hogai.session_summaries.utils import load_custom_template
from ee.hogai.utils.yaml import load_yaml_from_raw_llm_content
from ee.hogai.videos.session_moments import SessionMomentInput, SessionMomentOutput, SessionMomentsLLMAnalyzer
from ee.models.session_summaries import SessionSummaryRunMeta, SessionSummaryVisualConfirmationResult

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _SessionSummaryVideoValidationFieldToUpdate:
    """Field which value could be updated based on the video-based validation"""

    path: str
    current_value: str | None
    new_value: str | None


class SessionSummaryVideoValidator:
    def __init__(
        self,
        *,
        session_id: str,
        summary: SessionSummarySerializer,
        run_metadata: dict[str, Any],
        team_id: int,
        user: User,
        trace_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.team_id = team_id
        self.user = user
        self.summary = summary
        self.run_metadata = run_metadata
        self.trace_id = trace_id
        self.moments_analyzer = SessionMomentsLLMAnalyzer(
            session_id=session_id, team_id=team_id, user=user, trace_id=trace_id
        )
        self._fields_to_validate = [
            "description",  # To understand what the assumption was, before validation
            SessionSummaryIssueTypes.EXCEPTION.value,
            SessionSummaryIssueTypes.ABANDONMENT.value,
            SessionSummaryIssueTypes.CONFUSION.value,
        ]

    async def validate_session_summary_with_videos(
        self, model_to_use: str
    ) -> tuple[SessionSummarySerializer, SessionSummaryRunMeta] | None:
        """Validate the session summary with videos"""
        # Find the events that would value from video validation (for example, blocking exceptions)
        events_to_validate, fields_to_update = self._pick_events_to_validate()
        if not events_to_validate:
            # No events to validate, no need to generate updates
            return None
        # Prepare input for video validation
        moments_input = self._prepare_moments_input(events_to_validate=events_to_validate)
        # Generate videos and ask LLM to describe them
        # Not using semaphore inside moments analyzer as a single session summary won't have many blocking exceptions to validate
        # TODO: If exceptions are close to each other - generate and reuse a single video instead of multiple overlapping ones
        description_results = await self.moments_analyzer.analyze(
            moments_input=moments_input,
            expires_after_days=EXPIRES_AFTER_DAYS,
            failed_moments_min_ratio=FAILED_MOMENTS_MIN_RATIO,
        )
        if not description_results:
            # No description results generated, no need to generate updates
            return None
        # Generate updates through LLM to update specific fields based on the video-based results from the previous step
        updates_result = await self._generate_updates(
            description_results=description_results, fields_to_update=fields_to_update, model_to_use=model_to_use
        )
        if updates_result is None:
            # No updates generated, no need to apply them
            return None
        # Apply updates to the summary object
        updated_summary = self._apply_updates(updates_result=updates_result)
        # Generate updated run metadata
        updated_run_metadata = self._generate_updates_run_metadata(
            description_results=description_results, events_to_validate=events_to_validate
        )
        # TODO: Remove after testing
        with open("initial_summary.json", "w") as f:
            json.dump(self.summary.data, f, indent=4)
        with open("updated_summary.json", "w") as f:
            json.dump(updated_summary.data, f, indent=4)
        with open("updates_result.json", "w") as f:
            json.dump(updates_result, f, indent=4)
        # Return the updated summary and the run metadata
        return updated_summary, updated_run_metadata

    def _generate_video_description_prompt(self, event: EnrichedKeyActionSerializer) -> str:
        """Generate a prompt for validating a video"""
        template_dir = Path(__file__).parent / "templates" / "video-validation"
        prompt = load_custom_template(
            template_dir,
            "description-prompt.djt",
            {"EVENT_DESCRIPTION": event.data["description"]},
        )
        return prompt

    def _pick_events_to_validate(
        self,
    ) -> tuple[list[tuple[str, EnrichedKeyActionSerializer]], list[_SessionSummaryVideoValidationFieldToUpdate]]:
        # Pick blocking exceptions to generate videos for
        events_to_validate: list[tuple[str, EnrichedKeyActionSerializer]] = []
        # Keep track of the blocks that would need an update based on the video-based results
        fields_to_update_mapping: dict[str, _SessionSummaryVideoValidationFieldToUpdate] = {}
        for ki, key_actions in enumerate(self.summary.data.get("key_actions", [])):
            segment_index = key_actions["segment_index"]
            for ei, event in enumerate(key_actions.get("events", [])):
                # TODO: Decide if it adds to value to check other issues also (not just blocking issues)
                if event.get(SessionSummaryIssueTypes.EXCEPTION.value) != SessionSummaryExceptionTypes.BLOCKING.value:
                    continue
                # Keep only blocking exceptions
                validated_event = EnrichedKeyActionSerializer(data=event)
                validated_event.is_valid(raise_exception=True)
                # Collect the fields to validate and, potentially,update, and their current values
                for field in self._fields_to_validate:
                    field_path = f"key_actions.{ki}.events.{ei}.{field}"
                    # Avoid storing the same field multiple times
                    if not fields_to_update_mapping.get(field_path):
                        fields_to_update_mapping[field_path] = _SessionSummaryVideoValidationFieldToUpdate(
                            path=field_path,
                            current_value=event.get(field),
                            new_value=None,
                        )
                # Related segment outcome
                for field in ["success", "summary"]:
                    field_path = f"segment_outcomes.{segment_index}.{field}"
                    if not fields_to_update_mapping.get(field_path):
                        fields_to_update_mapping[field_path] = _SessionSummaryVideoValidationFieldToUpdate(
                            path=field_path,
                            current_value=self.summary.data["segment_outcomes"][segment_index].get(field),
                            new_value=None,
                        )
                field_path = f"segments.{segment_index}.name"
                if not fields_to_update_mapping.get(field_path):
                    fields_to_update_mapping[field_path] = _SessionSummaryVideoValidationFieldToUpdate(
                        path=field_path,
                        current_value=self.summary.data["segments"][segment_index].get("name"),
                        new_value=None,
                    )
                # Session outcome
                for field in ["success", "description"]:
                    field_path = f"session_outcome.{field}"
                    if not fields_to_update_mapping.get(field_path):
                        fields_to_update_mapping[field_path] = _SessionSummaryVideoValidationFieldToUpdate(
                            path=field_path,
                            current_value=self.summary.data["session_outcome"].get(field),
                            new_value=None,
                        )
                # Generate prompt
                prompt = self._generate_video_description_prompt(event=validated_event)
                events_to_validate.append((prompt, validated_event))
        if not events_to_validate:
            # No blocking issues detected in the summary, no need to validate
            return [], []
        # Sort fields to update by path
        fields_to_update_mapping = dict(sorted(fields_to_update_mapping.items(), key=lambda x: x[0]))
        fields_to_update = list(fields_to_update_mapping.values())
        return events_to_validate, fields_to_update

    def _prepare_moment_input_from_summary_event(
        self, prompt: str, event: EnrichedKeyActionSerializer
    ) -> SessionMomentInput | None:
        event_id = event.data["event_id"]  # Using event id (hex) instead of uuid for simpler input/output
        ms_from_start = event.data.get("milliseconds_since_start")
        if ms_from_start is None:
            logger.error(
                f"Milliseconds since start not found in the event {event.data['event_uuid']} for session {self.session_id}"
                "when generating video for validating session summary",
            )
            return None
        event_timestamp = floor(ms_from_start / 1000)
        # Start a video a couple of seconds before the event
        moment_timestamp = max(0, event_timestamp - SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO)
        return SessionMomentInput(
            moment_id=event_id,
            timestamp_s=moment_timestamp,
            duration_s=VALIDATION_VIDEO_DURATION,
            prompt=prompt,
        )

    def _prepare_moments_input(
        self, events_to_validate: list[tuple[str, EnrichedKeyActionSerializer]]
    ) -> list[SessionMomentInput]:
        """Prepare input for video validation from events to validate"""
        moments_input = [
            moment
            for prompt, event in events_to_validate
            if (moment := self._prepare_moment_input_from_summary_event(prompt=prompt, event=event))
        ]
        return moments_input

    def _generate_video_validation_prompts(
        self,
        description_results: list[SessionMomentOutput],
        fields_to_update: list[_SessionSummaryVideoValidationFieldToUpdate],
    ) -> tuple[str, str]:
        """Generate a prompt for validating a video"""
        template_dir = Path(__file__).parent / "templates" / "video-validation"
        # Remove excessive content (UUIDs, etc.) from session summary to not feed LLM excessive info
        mini_summary = IntermediateSessionSummarySerializer(data=self.summary.data)
        mini_summary.is_valid(raise_exception=True)
        # Keep only moment ids and descriptions to not feed LLM excessive info
        moment_descriptions = {dr.moment_id: dr.video_description for dr in description_results}
        # Load data into the prompt
        prompt = load_custom_template(
            template_dir,
            "validation-prompt.djt",
            {
                "ORIGINAL_SUMMARY": json.dumps(mini_summary.data),
                "VALIDATION_RESULTS": json.dumps(moment_descriptions),
                "FIELDS_TO_UPDATE": yaml.dump(
                    [asdict(x) for x in fields_to_update], allow_unicode=True, sort_keys=False
                ),
            },
        )
        # Get system prompt
        system_prompt = load_custom_template(
            template_dir,
            "validation-system-prompt.djt",
        )
        return prompt, system_prompt

    async def _generate_updates(
        self,
        description_results: list[SessionMomentOutput],
        fields_to_update: list[_SessionSummaryVideoValidationFieldToUpdate],
        model_to_use: str,
    ) -> list[dict[str, str]] | None:
        # Generate prompt for video validation
        validation_prompt, system_prompt = self._generate_video_validation_prompts(
            description_results=description_results,
            fields_to_update=fields_to_update,
        )
        # Call LLM with the validation prompt
        updates_raw = await call_llm(
            input_prompt=validation_prompt,
            user_key=self.user.id,
            session_id=self.session_id,
            model=model_to_use,
            system_prompt=system_prompt,
            trace_id=self.trace_id or str(uuid.uuid4()),
        )
        updates_content = get_raw_content(updates_raw)
        if not updates_content:
            logger.exception(
                f"No updates content found for session {self.session_id} when validating session summary with videos"
            )
            return None
        updates_result = load_yaml_from_raw_llm_content(raw_content=updates_content, final_validation=True)
        updates_result = cast(list[dict[str, str]], updates_result)
        return updates_result

    def _apply_updates(self, updates_result: list[dict[str, str]]) -> SessionSummarySerializer:
        """Apply updates to the summary"""
        summary_to_update = copy.deepcopy(self.summary.data)
        for field in updates_result:
            # Ensure the path exists and wasn't hallucinated
            try:
                find_value(target=summary_to_update, spec=field["path"])
            except PathAccessError:
                logger.exception(
                    f"Field {field['path']} not found in the session summary to update for the session {self.session_id}, skipping"
                )
                continue
            # Assign the new value to the summary
            # Allow None, as it's valid (for example, exception changed to None from `blocking`)
            assign_value(obj=summary_to_update, path=field["path"], val=field["new_value"])
        updated_summary = SessionSummarySerializer(data=summary_to_update)
        updated_summary.is_valid(raise_exception=True)
        return updated_summary

    def _generate_updates_run_metadata(
        self,
        description_results: list[SessionMomentOutput],
        events_to_validate: list[tuple[str, EnrichedKeyActionSerializer]],
    ) -> SessionSummaryRunMeta:
        """Store the updates to the summary in the database, together with the validation results"""
        events_id_to_uuid = {event.data["event_id"]: event.data["event_uuid"] for _, event in events_to_validate}
        # Prepare data on the video generation results
        validation_confirmation_results = [
            SessionSummaryVisualConfirmationResult.from_session_moment_output(
                session_moment_output=description_result,
                event_uuid=events_id_to_uuid[description_result.moment_id],
            )
            for description_result in description_results
        ]
        # Prepare run metadata
        model_used = cast(str, self.run_metadata["model_used"])
        return SessionSummaryRunMeta(
            model_used=model_used,
            visual_confirmation=True,
            visual_confirmation_results=validation_confirmation_results,
        )
