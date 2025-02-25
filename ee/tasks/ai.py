import cohere
import posthoganalytics
import structlog
import turbopuffer as tpuf
from celery import shared_task
from django.db.models import F
from django.utils import timezone

from ee.hogai.summarizers.chains import batch_summarize_actions
from posthog.models import Action

logger = structlog.get_logger(__name__)


cohere_client = cohere.ClientV2()


@shared_task
def summarize_actions_batch(team_id: int, action_ids: list[int]):
    """
    Summarize actions in batches, embed the summaries, and save them to the vector database.
    TurboPuffer supports only a single upsert request per namespace, so we batch by team.
    """
    actions = Action.objects.filter(id__in=action_ids)

    start_dt = timezone.now()
    summaries = batch_summarize_actions(actions)

    logger.info("summarized actions", team_id=team_id, action_ids=action_ids)

    models_to_update = []
    for action, maybe_summary in zip(actions, summaries):
        if isinstance(maybe_summary, BaseException):
            posthoganalytics.capture_exception(maybe_summary, context={"action_id": action.id})
            continue
        action.last_summarized_at = start_dt
        action.summary = maybe_summary
        models_to_update.append(action)

    embeddings_response = cohere_client.embed(
        texts=[action.summary for action in models_to_update],
        model="embed-english-v3.0",
        input_type="search_document",
        embedding_types=["float"],
    )

    logger.info("embedded actions", team_id=team_id, action_ids=action_ids)

    if not embeddings_response.embeddings.float_:
        raise ValueError("No embeddings found")

    ns = tpuf.Namespace(f"org:{team_id}")
    ns.upsert(
        ids=[action.id for action in models_to_update],
        vectors=embeddings_response.embeddings.float_,
        attributes={
            "name": [action.name for action in models_to_update],
            "description": [action.description for action in models_to_update],
            "domain": ["action"] * len(models_to_update),
            "summary": [action.summary for action in models_to_update],
        },
        distance_metric="cosine_distance",
        schema={
            "name": {
                "type": "string",
                "full_text_search": True,
            },
            "description": {
                "type": "string",
                "full_text_search": True,
            },
            "summary": {
                "type": "string",
                "full_text_search": True,
            },
        },
    )

    Action.objects.bulk_update(models_to_update, ["last_summarized_at", "summary"])

    logger.info("upserted embeddings", team_id=team_id, action_ids=action_ids)


MAX_EMBEDDING_BATCH_SIZE = 96


@shared_task
def summarize_actions():
    actions_to_summarize = (
        Action.objects.values("team_id")
        .annotate(
            actions=F("id"),
        )
        .filter(updated_at__gte=F("last_summarized_at"))
    )

    for action in actions_to_summarize:
        actions = action["actions"]
        team_id = actions["team_id"]

        for i in range(0, len(actions), MAX_EMBEDDING_BATCH_SIZE):
            action_ids = actions[i : i + MAX_EMBEDDING_BATCH_SIZE]
            summarize_actions_batch.delay(team_id, action_ids)
