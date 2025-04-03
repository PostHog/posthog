from ee.session_recordings.ai.llm import get_llm_summary
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData, shorten_url
from ee.session_recordings.session_summary.utils import (
    load_session_metadata_from_json,
    load_sesssion_recording_events_from_csv,
)
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording
from django.template.loader import get_template


class ReplaySummarizer:
    def __init__(self, recording: SessionRecording, user: User, team: Team):
        self.recording = recording
        self.user = user
        self.team = team

    @staticmethod
    def _get_session_metadata(session_id: str, team: Team) -> dict:
        # TODO: Uncomment after testing with production data
        # session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
        # if not session_metadata:
        #     raise ValueError(f"no session metadata found for session_id {session_id}")
        # Load session metadata from JSON to load with production data.
        # TODO: Remove before merging, using to test with production data
        session_metadata = load_session_metadata_from_json(
            "/Users/woutut/Documents/Code/posthog/playground/single-session-metadata_0195f10e-7c84-7944-9ea2-0303a4b37af7.json"
        )
        # Convert session_metadata to a dict, so that we can amend its values freely
        session_metadata_dict = dict(session_metadata)
        return session_metadata_dict

    @staticmethod
    def _get_session_events(session_id: str, team: Team) -> tuple[list[str], list[tuple[str | None, ...]]]:
        # TODO: Uncomment after testing with production data
        # session_events = SessionReplayEvents().get_events(
        #     session_id=str(session_id),
        #     team=team,
        #     metadata=session_metadata,
        #     events_to_ignore=[
        #         "$feature_flag_called",
        #     ],
        # )
        # Load session events from CSV to load with production data.
        # TODO: Remove before merging, using to test with production data
        session_events = load_sesssion_recording_events_from_csv(
            "/Users/woutut/Documents/Code/posthog/playground/single-session-csv-export_0195f10e-7c84-7944-9ea2-0303a4b37af7.csv"
        )
        if not session_events or not session_events[0] or not session_events[1]:
            raise ValueError(f"no events found for session_id {session_id}")
        return session_events[0], session_events[1]

    def _generate_prompt(
        self, session_metadata: dict, session_events_columns: list[str], session_events: list[tuple[str | None, ...]]
    ) -> str:
        prompt_data = SessionSummaryPromptData()
        prompt_data.load_session_data(session_events, session_metadata, session_events_columns)
        # Reverse mappings for easier reference in the prompt.
        full_url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
        window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
        # Keep shortened URLs for the prompt to reduce the number of tokens
        url_mapping_reversed = {k: shorten_url(v) for k, v in full_url_mapping_reversed.items()}
        # Render all templates
        summary_template = get_template(f"session_summaries/single-replay_base-prompt.djt")
        summary_example = get_template(f"session_summaries/single-replay_example.yml").render()
        rendered_summary_prompt = summary_template.render(
            {
                "EVENTS_COLUMNS": prompt_data.columns,
                "EVENTS_DATA": prompt_data.results,
                "SESSION_METADATA": prompt_data.metadata.to_dict(),
                "URL_MAPPING": url_mapping_reversed,
                "WINDOW_ID_MAPPING": window_mapping_reversed,
                "SUMMARY_EXAMPLE": summary_example,
            }
        )
        # TODO: Remove after testing
        with open("wakawaka.txt", "w") as f:
            f.write(rendered_summary_prompt)
        return rendered_summary_prompt

    def summarize_recording(self):
        timer = ServerTimingsGathered()
        # TODO Learn how to make data collection for prompt as async as possible to improve latency
        with timer("get_metadata"):
            session_metadata = self._get_session_metadata(self.recording.session_id, self.team)
        with timer("get_events"):
            session_events_columns, session_events = self._get_session_events(self.recording.session_id, self.team)
        # TODO Get web analytics data on URLs to better understand what the user was doing
        # related to average visitors of the same pages (left the page too fast, unexpected bounce, etc.).
        # Keep in mind that in-app behavior (like querying insights a lot) differs from the web (visiting a lot of pages).
        with timer("generate_prompt"):
            rendered_summary_prompt = self._generate_prompt(session_metadata, session_events_columns, session_events)
        with timer("openai_completion"):
            session_summary = get_llm_summary(rendered_summary_prompt, self.user, self.recording.session_id)
        # TODO Make the output streamable (the main reason behing using YAML
        # to keep it partially parsable to avoid waiting for the LLM to finish)
        return {"content": session_summary.data, "timings": timer.get_all_timings()}
