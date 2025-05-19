from collections.abc import Generator
import json
from pathlib import Path

import structlog
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.session_recordings.session_summary.input_data import (
    add_context_and_filter_events,
    get_session_events,
    get_session_metadata,
)
from ee.session_recordings.session_summary.llm.consume import stream_llm_session_summary
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.utils import load_custom_template, serialize_to_sse_event, shorten_url
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.settings import SERVER_GATEWAY_INTERFACE

logger = structlog.get_logger(__name__)


class ReplaySummarizer:
    def __init__(self, session_id: str, user: User, team: Team, local_reads_prod: bool = False):
        self.session_id = session_id
        self.user = user
        self.team = team
        self.local_reads_prod = local_reads_prod

    def _generate_prompt(
        self,
        prompt_data: SessionSummaryPromptData,
        url_mapping_reversed: dict[str, str],
        window_mapping_reversed: dict[str, str],
    ) -> tuple[str, str]:
        # Keep shortened URLs for the prompt to reduce the number of tokens
        short_url_mapping_reversed = {k: shorten_url(v) for k, v in url_mapping_reversed.items()}
        # Render all templates
        template_dir = Path(__file__).parent / "templates" / "identify-objectives"
        system_prompt = load_custom_template(template_dir, f"system-prompt.djt")
        summary_example = load_custom_template(template_dir, f"example.yml")
        summary_prompt = load_custom_template(
            template_dir,
            f"prompt.djt",
            {
                "EVENTS_DATA": json.dumps(prompt_data.results),
                "SESSION_METADATA": json.dumps(prompt_data.metadata.to_dict()),
                "URL_MAPPING": json.dumps(short_url_mapping_reversed),
                "WINDOW_ID_MAPPING": json.dumps(window_mapping_reversed),
                "SUMMARY_EXAMPLE": summary_example,
            },
        )
        return summary_prompt, system_prompt

    def summarize_recording(self) -> Generator[str, None, None]:
        timer = ServerTimingsGathered()
        # TODO Learn how to make data collection for prompt as async as possible to improve latency
        with timer("get_metadata"):
            session_metadata = get_session_metadata(
                session_id=self.session_id,
                team=self.team,
                local_reads_prod=self.local_reads_prod,
            )
        try:
            with timer("get_events"):
                session_events_columns, session_events = get_session_events(
                    team=self.team,
                    session_metadata=session_metadata,
                    session_id=self.session_id,
                    local_reads_prod=self.local_reads_prod,
                )
        # Real-time replays could have no events yet, so we need to handle that case and show users a meaningful message
        except ValueError as e:
            raw_error_message = str(e)
            if "No events found for session_id" in raw_error_message:
                # Returning a generator (instead of yielding) to keep the consistent behavior for later iter-to-async conversion
                return (
                    msg
                    for msg in [
                        serialize_to_sse_event(
                            event_label="session-summary-error",
                            event_data="No events found for this replay yet. Please try again in a few minutes.",
                        )
                    ]
                )
            # Re-raise unexpected exceptions
            raise
        with timer("add_context_and_filter"):
            session_events_columns, session_events = add_context_and_filter_events(
                session_events_columns, session_events
            )

        # TODO Get web analytics data on URLs to better understand what the user was doing
        # related to average visitors of the same pages (left the page too fast, unexpected bounce, etc.).
        # Keep in mind that in-app behavior (like querying insights a lot) differs from the web (visiting a lot of pages).

        # TODO Get product analytics data on custom events/funnels/conversions
        # to understand what actions are seen as valuable or are the part of the conversion flow

        with timer("generate_prompt"):
            prompt_data = SessionSummaryPromptData()
            simplified_events_mapping = prompt_data.load_session_data(
                raw_session_events=session_events,
                # Convert to a dict, so that we can amend its values freely
                raw_session_metadata=dict(session_metadata),
                raw_session_columns=session_events_columns,
                session_id=self.session_id,
            )
            if not prompt_data.metadata.start_time:
                raise ValueError(f"No start time found for session_id {self.session_id} when generating the prompt")
            # Reverse mappings for easier reference in the prompt.
            url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
            window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
            summary_prompt, system_prompt = self._generate_prompt(
                prompt_data, url_mapping_reversed, window_mapping_reversed
            )

        # TODO: Track the timing for streaming (inside the function, start before the request, end after the last chunk is consumed)
        # with timer("openai_completion"):
        # return {"content": session_summary.data, "timings_header": timer.to_header_string()}

        session_summary_generator = stream_llm_session_summary(
            summary_prompt=summary_prompt,
            user=self.user,
            allowed_event_ids=list(simplified_events_mapping.keys()),
            session_id=self.session_id,
            simplified_events_mapping=simplified_events_mapping,
            simplified_events_columns=prompt_data.columns,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            session_metadata=prompt_data.metadata,
            system_prompt=system_prompt,
        )
        return session_summary_generator

    def stream_recording_summary(self):
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            return self._astream()
        return self.summarize_recording()

    def _astream(self):
        return SyncIterableToAsync(self.summarize_recording())
