from datetime import datetime
from pathlib import Path

import structlog
from ee.session_recordings.ai.llm import get_raw_llm_session_summary
from ee.session_recordings.ai.output_data import enrich_raw_session_summary_with_events_meta
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.utils import load_custom_template, shorten_url
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording


logger = structlog.get_logger(__name__)


class ReplaySummarizer:
    def __init__(self, recording: SessionRecording, user: User, team: Team):
        self.recording = recording
        self.user = user
        self.team = team

    @staticmethod
    def _get_session_metadata(session_id: str, team: Team) -> RecordingMetadata:
        session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
        if not session_metadata:
            raise ValueError(f"no session metadata found for session_id {session_id}")
        return session_metadata

    @staticmethod
    def _get_session_events(
        session_id: str, session_metadata: RecordingMetadata, team: Team
    ) -> tuple[list[str], list[list[str | datetime]]]:
        session_events_columns, session_events = SessionReplayEvents().get_events(
            session_id=str(session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )
        if not session_events_columns or not session_events:
            raise ValueError(f"no events found for session_id {session_id}")
        return session_events_columns, session_events

    def _generate_prompt(
        self,
        prompt_data: SessionSummaryPromptData,
        url_mapping_reversed: dict[str, str],
        window_mapping_reversed: dict[str, str],
    ) -> str:
        # Keep shortened URLs for the prompt to reduce the number of tokens
        short_url_mapping_reversed = {k: shorten_url(v) for k, v in url_mapping_reversed.items()}
        # Render all templates
        # TODO Optimize prompt (reduce input count, simplify instructions, focus on quality of the summary)
        # One of the solutions could be to chain prompts to focus on events/tags/importance one by one, to avoid overloading the main prompt
        template_dir = Path(__file__).parent / "templates"
        summary_example = load_custom_template(template_dir, f"single-replay_example.yml")
        summary_prompt = load_custom_template(
            template_dir,
            f"single-replay_base-prompt.djt",
            {
                "EVENTS_COLUMNS": prompt_data.columns,
                "EVENTS_DATA": prompt_data.results,
                "SESSION_METADATA": prompt_data.metadata.to_dict(),
                "URL_MAPPING": short_url_mapping_reversed,
                "WINDOW_ID_MAPPING": window_mapping_reversed,
                "SUMMARY_EXAMPLE": summary_example,
            },
        )
        return summary_prompt

    def summarize_recording(self):
        timer = ServerTimingsGathered()

        # TODO Learn how to make data collection for prompt as async as possible to improve latency
        with timer("get_metadata"):
            session_metadata = self._get_session_metadata(self.recording.session_id, self.team)

        with timer("get_events"):
            # TODO: Add filter to skip some types of events that are not relevant for the summary, but increase the number of tokens
            # Analyze more events one by one for better context, consult with the team
            session_events_columns, session_events = self._get_session_events(
                self.recording.session_id, session_metadata, self.team
            )

        # TODO Get web analytics data on URLs to better understand what the user was doing
        # related to average visitors of the same pages (left the page too fast, unexpected bounce, etc.).
        # Keep in mind that in-app behavior (like querying insights a lot) differs from the web (visiting a lot of pages).

        with timer("generate_prompt"):
            prompt_data = SessionSummaryPromptData()
            simplified_events_mapping = prompt_data.load_session_data(
                raw_session_events=session_events,
                # Convert to a dict, so that we can amend its values freely
                raw_session_metadata=dict(session_metadata),
                raw_session_columns=session_events_columns,
                session_id=self.recording.session_id,
            )
            if not prompt_data.metadata.start_time:
                raise ValueError(
                    f"No start time found for session_id {self.recording.session_id} when generating the prompt"
                )
            # Reverse mappings for easier reference in the prompt.
            url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
            window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
            rendered_summary_prompt = self._generate_prompt(prompt_data, url_mapping_reversed, window_mapping_reversed)

        with timer("openai_completion"):
            raw_session_summary = get_raw_llm_session_summary(
                rendered_summary_template=rendered_summary_prompt,
                user=self.user,
                allowed_event_ids=list(simplified_events_mapping.keys()),
                session_id=self.recording.session_id,
            )
        # Enrich the session summary with events metadata
        # TODO Ensure only important events are picked (instead of 5 events for the first 1 minute and then 5 for the rest)
        session_summary = enrich_raw_session_summary_with_events_meta(
            raw_session_summary=raw_session_summary,
            simplified_events_mapping=simplified_events_mapping,
            simplified_events_columns=prompt_data.columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_start_time=prompt_data.metadata.start_time,
            session_id=self.recording.session_id,
        )

        # TODO: Calculate tag/error stats for the session manually
        # to use it later for grouping/suggesting (and showing overall stats)

        # TODO Make the output streamable (the main reason behind using YAML
        # to keep it partially parsable to avoid waiting for the LLM to finish)

        return {"content": session_summary.data, "timings": timer.get_all_timings()}
