from datetime import datetime
from typing import Any

import structlog
from ee.session_recordings.ai.llm import get_raw_llm_session_summary
from ee.session_recordings.ai.output_data import enrich_raw_session_summary_with_events_meta
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.utils import (
    load_session_metadata_from_json,
    load_sesssion_recording_events_from_csv,
    shorten_url,
)
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording
from django.template.loader import get_template


logger = structlog.get_logger(__name__)


class ReplaySummarizer:
    def __init__(self, recording: SessionRecording, user: User, team: Team):
        self.recording = recording
        self.user = user
        self.team = team

    @staticmethod
    def _get_session_metadata(session_id: str, team: Team) -> dict[str, Any]:
        # # TODO: Switch to using it after testing with production data
        # live_session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
        # if not live_session_metadata:
        #     raise ValueError(f"no session metadata found for session_id {session_id}")
        # # Convert to a dict, so that we can amend its values freely
        # live_session_metadata_dict = dict(live_session_metadata)
        logger.debug(f"Session id: {session_id}, team: {team}")

        # TODO: Remove before merging, using to test with production data
        # Load session metadata from JSON to load with production data.
        session_metadata_dict = load_session_metadata_from_json(
            "/Users/woutut/Documents/Code/posthog/playground/single-session-metadata_0195f10e-7c84-7944-9ea2-0303a4b37af7.json"
        )
        return session_metadata_dict

    @staticmethod
    def _get_session_events(
        session_id: str, session_metadata: dict, team: Team
    ) -> tuple[list[str], list[list[str | datetime]]]:
        # # TODO: Switch to using it after testing with production data
        # live_session_events = SessionReplayEvents().get_events(
        #     session_id=str(session_id),
        #     team=team,
        #     metadata=session_metadata,
        #     events_to_ignore=[
        #         "$feature_flag_called",
        #     ],
        # )
        logger.debug(f"Session metadata: {session_metadata}, team: {team}")

        # TODO: Remove before merging, using to test with production data
        # Load session events from CSV to load with production data.
        session_events_columns, session_events = load_sesssion_recording_events_from_csv(
            "/Users/woutut/Documents/Code/posthog/playground/single-session-csv-export_0195f10e-7c84-7944-9ea2-0303a4b37af7.csv"
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
        summary_template = get_template(f"session_summaries/single-replay_base-prompt.djt")
        summary_example = get_template(f"session_summaries/single-replay_example.yml").render()
        rendered_summary_prompt = summary_template.render(
            {
                "EVENTS_COLUMNS": prompt_data.columns,
                "EVENTS_DATA": prompt_data.results,
                "SESSION_METADATA": prompt_data.metadata.to_dict(),
                "URL_MAPPING": short_url_mapping_reversed,
                "WINDOW_ID_MAPPING": window_mapping_reversed,
                "SUMMARY_EXAMPLE": summary_example,
            }
        )
        return rendered_summary_prompt

    def summarize_recording(self):
        timer = ServerTimingsGathered()

        # TODO Learn how to make data collection for prompt as async as possible to improve latency
        with timer("get_metadata"):
            session_metadata = self._get_session_metadata(self.recording.session_id, self.team)
        with timer("get_events"):
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
                raw_session_metadata=session_metadata,
                raw_session_columns=session_events_columns,
                session_id=self.recording.session_id,
            )
            # Reverse mappings for easier reference in the prompt.
            url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
            window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
            rendered_summary_prompt = self._generate_prompt(prompt_data, url_mapping_reversed, window_mapping_reversed)
            # TODO Remove after testing
            # with open("wakawaka_input.txt", "w") as f:
            #     f.write(rendered_summary_prompt)

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

        # TODO Make the output streamable (the main reason behing using YAML
        # to keep it partially parsable to avoid waiting for the LLM to finish)

        # TODO Remove after testing
        # import json

        # with open("wakawaka_output.json", "w") as f:
        #     f.write(json.dumps(session_summary.data, indent=4))

        return {"content": session_summary.data, "timings": timer.get_all_timings()}
