from datetime import datetime
from pathlib import Path

import structlog
from ee.session_recordings.ai.llm import call_llm
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.base_summarizer import BaseReplaySummarizer
from ee.session_recordings.session_summary.utils import load_custom_template, shorten_url
from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording

logger = structlog.get_logger(__name__)

class ReplayObjectivesIdentifier(BaseReplaySummarizer):
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

    def identify_objectives(self) -> None:
        timer = ServerTimingsGathered()
        with timer("get_metadata"):
            session_metadata = self._get_session_metadata(self.recording.session_id, self.team)
        with timer("get_events"):
            # Analyze more events one by one for better context, consult with the team
            session_events_columns, session_events = self._get_session_events(
                self.recording.session_id, session_metadata, self.team
            )
        with timer("generate_prompt"):
            prompt_data = SessionSummaryPromptData()
            # TODO: Use later for enriching the response with event metadata?
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
            summary_prompt, system_prompt = self._generate_prompt(prompt_data, url_mapping_reversed, window_mapping_reversed)

        with timer("openai_completion"):
            try:
                raw_llm_response = call_llm(
                    input_prompt=summary_prompt,
                    user_key=self.user.pk,
                    session_id=self.recording.session_id,
                    system_prompt=system_prompt,
                )
                content = raw_llm_response.choices[0].message.content
            except Exception as e:
                logger.exception(f"Error calling LLM for session_id {self.recording.session_id} by user {self.user.pk}, retrying: {e}")
                raise e

        # Store the results on success
        results_base_dir = "/Users/woutut/Documents/Code/posthog/playground/identify-objectives-experiments"
        # Count how many child directories there are in the results_base_dir
        child_dirs = [d for d in Path(results_base_dir).iterdir() if d.is_dir()]
        datetime_marker = f"{len(child_dirs)}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        current_experiment_dir = Path(results_base_dir) / datetime_marker
        current_experiment_dir.mkdir(parents=True, exist_ok=True)

        # Store the prompt and response for results tracking
        with open(current_experiment_dir / f"prompt_{datetime_marker}.txt", "w") as f:
            f.write(summary_prompt)
        with open(current_experiment_dir / f"response_{datetime_marker}.yml", "w") as f:
            f.write(content)
        template_dir = Path(__file__).parent / "templates" / "identify-objectives"
        with open(template_dir / "prompt.djt", "r") as fr:
            with open(current_experiment_dir / f"prompt_template_{datetime_marker}.txt", "w") as fw: 
                fw.write(fr.read())
        with open(template_dir / "system-prompt.djt", "r") as fr:
            with open(current_experiment_dir / f"system_prompt_{datetime_marker}.txt", "w") as fw: 
                fw.write(fr.read())
        with open(template_dir / "example.yml", "r") as fr:
            with open(current_experiment_dir / f"example_{datetime_marker}.yml", "w") as fw: 
                fw.write(fr.read())

        # return {"content": "", "timings": timer.get_all_timings()}
        return None