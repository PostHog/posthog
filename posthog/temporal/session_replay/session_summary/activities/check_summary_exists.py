import temporalio

from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs

from ee.models.session_summaries import SingleSessionSummary


@temporalio.activity.defn
async def check_summary_exists_activity(inputs: SingleSessionSummaryInputs) -> bool:
    summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=[inputs.session_id],
        extra_summary_context=inputs.extra_summary_context,
    )
    return bool(summary_exists.get(inputs.session_id))
