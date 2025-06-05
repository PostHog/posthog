import asyncio
from dataclasses import dataclass
import aiohttp
import temporalio
import datetime as dt

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import connect


@dataclass(frozen=True, kw_only=True)
class SessionSummaryInputs:
    session_id: str
    user_pk: int
    team_pk: int
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@temporalio.activity.defn
async def test_summary_activity(inputs: SessionSummaryInputs) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get("http://httpbin.org/get") as resp:
            return await resp.text()


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSessionWorkflow(PostHogWorkflow):
    # def _generate_prompt(
    #     self,
    #     prompt_data: SessionSummaryPromptData,
    #     url_mapping_reversed: dict[str, str],
    #     window_mapping_reversed: dict[str, str],
    #     extra_summary_context: ExtraSummaryContext | None,
    # ) -> tuple[str, str]:
    #     # Keep shortened URLs for the prompt to reduce the number of tokens
    #     short_url_mapping_reversed = {k: shorten_url(v) for k, v in url_mapping_reversed.items()}
    #     # Render all templates
    #     template_dir = Path(__file__).parent / "templates" / "identify-objectives"
    #     system_prompt = load_custom_template(
    #         template_dir,
    #         f"system-prompt.djt",
    #         {
    #             "FOCUS_AREA": extra_summary_context.focus_area if extra_summary_context else None,
    #         },
    #     )
    #     summary_example = load_custom_template(template_dir, f"example.yml")
    #     summary_prompt = load_custom_template(
    #         template_dir,
    #         f"prompt.djt",
    #         {
    #             "EVENTS_DATA": json.dumps(prompt_data.results),
    #             "SESSION_METADATA": json.dumps(prompt_data.metadata.to_dict()),
    #             "URL_MAPPING": json.dumps(short_url_mapping_reversed),
    #             "WINDOW_ID_MAPPING": json.dumps(window_mapping_reversed),
    #             "SUMMARY_EXAMPLE": summary_example,
    #             "FOCUS_AREA": extra_summary_context.focus_area if extra_summary_context else None,
    #         },
    #     )
    #     return summary_prompt, system_prompt

    @temporalio.workflow.run
    async def run(self, inputs: SessionSummaryInputs) -> str:
        test_content = await temporalio.workflow.execute_activity(
            test_summary_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=3),
                maximum_interval=dt.timedelta(seconds=10),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )
        return test_content
        # timer = ServerTimingsGathered()
        # with timer("get_metadata"):
        #     session_metadata = get_session_metadata(
        #         session_id=inputs.session_id,
        #         team_pk=inputs.team_pk,
        #         local_reads_prod=inputs.local_reads_prod,
        #     )
        # try:
        #     with timer("get_events"):
        #         session_events_columns, session_events = get_session_events(
        #             team_pk=inputs.team_pk,
        #             session_metadata=session_metadata,
        #             session_id=inputs.session_id,
        #             local_reads_prod=inputs.local_reads_prod,
        #         )
        # # Real-time replays could have no events yet, so we need to handle that case and show users a meaningful message
        # except ValueError as e:
        #     raw_error_message = str(e)
        #     if "No events found for session_id" in raw_error_message:
        #         # Returning a generator (instead of yielding) to keep the consistent behavior for later iter-to-async conversion
        #         return (
        #             msg
        #             for msg in [
        #                 serialize_to_sse_event(
        #                     event_label="session-summary-error",
        #                     event_data="No events found for this replay yet. Please try again in a few minutes.",
        #                 )
        #             ]
        #         )
        #     # Re-raise unexpected exceptions
        #     raise
        # with timer("add_context_and_filter"):
        #     session_events_columns, session_events = add_context_and_filter_events(
        #         session_events_columns, session_events
        #     )

        # # TODO Get web analytics data on URLs to better understand what the user was doing
        # # related to average visitors of the same pages (left the page too fast, unexpected bounce, etc.).
        # # Keep in mind that in-app behavior (like querying insights a lot) differs from the web (visiting a lot of pages).

        # # TODO Get product analytics data on custom events/funnels/conversions
        # # to understand what actions are seen as valuable or are the part of the conversion flow

        # with timer("generate_prompt"):
        #     prompt_data = SessionSummaryPromptData()
        #     simplified_events_mapping = prompt_data.load_session_data(
        #         raw_session_events=session_events,
        #         # Convert to a dict, so that we can amend its values freely
        #         raw_session_metadata=dict(session_metadata),
        #         raw_session_columns=session_events_columns,
        #         session_id=inputs.session_id,
        #     )
        #     if not prompt_data.metadata.start_time:
        #         raise ValueError(f"No start time found for session_id {inputs.session_id} when generating the prompt")
        #     # Reverse mappings for easier reference in the prompt.
        #     url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
        #     window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
        #     summary_prompt, system_prompt = self._generate_prompt(
        #         prompt_data, url_mapping_reversed, window_mapping_reversed, inputs.extra_summary_context
        #     )

        # # TODO: Track the timing for streaming (inside the function, start before the request, end after the last chunk is consumed)
        # # with timer("openai_completion"):
        # # return {"content": session_summary.data, "timings_header": timer.to_header_string()}

        # session_summary_generator = stream_llm_session_summary(
        #     summary_prompt=summary_prompt,
        #     user_pk=inputs.user_pk,
        #     allowed_event_ids=list(simplified_events_mapping.keys()),
        #     session_id=inputs.session_id,
        #     simplified_events_mapping=simplified_events_mapping,
        #     simplified_events_columns=prompt_data.columns,
        #     url_mapping_reversed=url_mapping_reversed,
        #     window_mapping_reversed=window_mapping_reversed,
        #     session_metadata=prompt_data.metadata,
        #     system_prompt=system_prompt,
        # )
        # return session_summary_generator


# async def stream_session_summary(session_id: str, user_pk: int, team_pk: int):
#     workflow = SummarizeSessionWorkflow()
#     async for chunk in workflow.run(SessionSummaryInputs(session_id=session_id, user_pk=user_pk, team_pk=team_pk)):
#         yield chunk


# def stream_session_summary_sync(session_id: str, user_pk: int, team_pk: int):
#     async def _stream():
#         async for chunk in stream_session_summary(session_id, user_pk, team_pk):
#             yield chunk

#     return asyncio.run(_stream())


def excectute_test_summarize_session(inputs: SessionSummaryInputs) -> str:
    client = asyncio.run(
        connect(
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TEMPORAL_NAMESPACE,
            server_root_ca_cert=settings.TEMPORAL_CLIENT_ROOT_CA,
            client_cert=settings.TEMPORAL_CLIENT_CERT,
            client_key=settings.TEMPORAL_CLIENT_KEY,
        )
    )
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    result = asyncio.run(
        client.execute_workflow(
            "summarize-session",
            inputs,
            id="123",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            retry_policy=retry_policy,
        )
    )
    return result
