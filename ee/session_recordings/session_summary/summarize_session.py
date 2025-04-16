from collections.abc import Generator
from pathlib import Path

import structlog
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.session_recordings.ai.llm import stream_raw_llm_session_summary
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.base_summarizer import BaseReplaySummarizer
from ee.session_recordings.session_summary.utils import load_custom_template, shorten_url
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.settings import SERVER_GATEWAY_INTERFACE

logger = structlog.get_logger(__name__)


class ReplaySummarizer(BaseReplaySummarizer):
    def __init__(self, recording: SessionRecording, user: User, team: Team):
        super().__init__(recording, user, team)

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
                "EVENTS_DATA": prompt_data.results,
                "SESSION_METADATA": prompt_data.metadata.to_dict(),
                "URL_MAPPING": short_url_mapping_reversed,
                "WINDOW_ID_MAPPING": window_mapping_reversed,
                "SUMMARY_EXAMPLE": summary_example,
            },
        )
        return summary_prompt, system_prompt

    def summarize_recording(self) -> Generator[str, None, None]:
        timer = ServerTimingsGathered()
        # TODO Learn how to make data collection for prompt as async as possible to improve latency
        with timer("get_metadata"):
            session_metadata = self._get_session_metadata(
                session_id=self.recording.session_id,
                team=self.team,
                # local_path="/Users/woutut/Documents/Code/posthog/playground/single-session-metadata_0195f10e-7c84-7944-9ea2-0303a4b37af7.json",
            )
        with timer("get_events"):
            # TODO: Add filter to skip some types of events that are not relevant for the summary, but increase the number of tokens
            # Analyze more events one by one for better context, consult with the team
            session_events_columns, session_events = self._get_session_events(
                session_id=self.recording.session_id,
                session_metadata=session_metadata,
                team=self.team,
                # local_path="/Users/woutut/Documents/Code/posthog/playground/single-session-csv-export_0195f10e-7c84-7944-9ea2-0303a4b37af7.csv",
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
            summary_prompt, system_prompt = self._generate_prompt(
                prompt_data, url_mapping_reversed, window_mapping_reversed
            )

        # with timer("openai_completion"):
        #     raw_session_summary = get_raw_llm_session_summary(
        #         summary_prompt=summary_prompt,
        #         user=self.user,
        #         allowed_event_ids=list(simplified_events_mapping.keys()),
        #         session_id=self.recording.session_id,
        #         system_prompt=system_prompt,
        #     )

        # Enrich the session summary with events metadata
        # session_summary = enrich_raw_session_summary_with_events_meta(
        #     raw_session_summary=raw_session_summary,
        #     simplified_events_mapping=simplified_events_mapping,
        #     simplified_events_columns=prompt_data.columns,
        #     url_mapping_reversed=url_mapping_reversed,
        #     window_mapping_reversed=window_mapping_reversed,
        #     session_start_time=prompt_data.metadata.start_time,
        #     session_id=self.recording.session_id,
        # )

        # TODO: Would it make sense to stream initial goal and outcome at the very start? Check if it makes a quality difference.
        session_summary_generator = stream_raw_llm_session_summary(
            summary_prompt=summary_prompt,
            user=self.user,
            allowed_event_ids=list(simplified_events_mapping.keys()),
            session_id=self.recording.session_id,
            system_prompt=system_prompt,
        )
        return session_summary_generator
        # # Store the results on success
        # results_base_dir = "/Users/woutut/Documents/Code/posthog/playground/identify-objectives-experiments"
        # # Count how many child directories there are in the results_base_dir
        # child_dirs = [d for d in Path(results_base_dir).iterdir() if d.is_dir()]
        # datetime_marker = f"{len(child_dirs)}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        # current_experiment_dir = Path(results_base_dir) / datetime_marker
        # current_experiment_dir.mkdir(parents=True, exist_ok=True)

        # # Store the prompt and response for results tracking
        # with open(current_experiment_dir / f"prompt_{datetime_marker}.txt", "w") as f:
        #     f.write(summary_prompt)
        # with open(current_experiment_dir / f"response_{datetime_marker}.yml", "w") as f:
        #     f.write(json.dumps(raw_session_summary.data, indent=4))
        # with open(current_experiment_dir / f"enriched_response_{datetime_marker}.yml", "w") as f:
        #     f.write(json.dumps(session_summary.data, indent=4))
        # with open(current_experiment_dir / f"timings_{datetime_marker}.json", "w") as fw:
        #     fw.write(json.dumps(timer.get_all_timings(), indent=4))
        # template_dir = Path(__file__).parent / "templates" / "identify-objectives"
        # with open(template_dir / "prompt.djt") as fr:
        #     with open(current_experiment_dir / f"prompt_template_{datetime_marker}.txt", "w") as fw:
        #         fw.write(fr.read())
        # with open(template_dir / "system-prompt.djt") as fr:
        #     with open(current_experiment_dir / f"system_prompt_{datetime_marker}.txt", "w") as fw:
        #         fw.write(fr.read())
        # with open(template_dir / "example.yml") as fr:
        #     with open(current_experiment_dir / f"example_{datetime_marker}.yml", "w") as fw:
        #         fw.write(fr.read())

        # TODO: Calculate tag/error stats for the session manually
        # to use it later for grouping/suggesting (and showing overall stats)

        # TODO: Make the output streamable (the main reason behind using YAML
        # to keep it partially parsable to avoid waiting for the LLM to finish)

        # TODO: Uncomment this after testing
        # return {"content": "", "timings": timer.get_all_timings()}
        # return None

    def stream_recording_summary(self):
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            return self._astream()
        return self.summarize_recording()

    def _astream(self):
        return SyncIterableToAsync(self.summarize_recording())
