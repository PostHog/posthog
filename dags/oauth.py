from datetime import timedelta
import time
import dagster
from django.conf import settings
from django.db.models import QuerySet, Model, Q
from django.utils import timezone
from dags.common import JobOwners
from posthog.models.oauth import OAuthAccessToken, OAuthGrant, OAuthIDToken, OAuthRefreshToken


def batch_delete_model(queryset: QuerySet, query: Q, context: dagster.OpExecutionContext, token_type: str) -> int:
    """Delete tokens in batches to avoid locking up the tables."""
    CLEAR_EXPIRED_TOKENS_BATCH_SIZE = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_SIZE", 1000)
    CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL = getattr(settings, "CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL", 0.1)

    current_no = start_no = queryset.count()
    context.log.info(f"Starting deletion of {start_no} {token_type}")

    while current_no:
        flat_queryset = queryset.values_list("id", flat=True)[:CLEAR_EXPIRED_TOKENS_BATCH_SIZE]
        batch_length = flat_queryset.count()

        if batch_length == 0:
            break

        queryset.model.objects.filter(id__in=list(flat_queryset)).delete()
        context.log.debug(f"{batch_length} {token_type} deleted, {current_no-batch_length} left")

        queryset = queryset.model.objects.filter(query)
        time.sleep(CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL)
        current_no = queryset.count()

    stop_no = queryset.model.objects.filter(query).count()
    deleted = start_no - stop_no
    return deleted


def clear_expired_tokens_by_type(
    model: type[Model], queries: dict[str, Q], context: dagster.OpExecutionContext
) -> dict[str, int]:
    """Clear expired tokens for a specific model type using multiple queries."""
    results = {}

    for query_name, query in queries.items():
        queryset = model.objects.filter(query)
        deleted_count = batch_delete_model(queryset, query, context, f"{model.__name__} {query_name}")
        results[query_name] = deleted_count
        context.log.info(f"{deleted_count} {model.__name__} {query_name} deleted")

    return results


@dagster.op
def clear_expired_oauth_tokens(context: dagster.OpExecutionContext) -> None:
    """
    Clear expired OAuth tokens from the database.
    This function deletes expired refresh tokens, access tokens, ID tokens, and grants
    """
    now = timezone.now()
    retention_cutoff = now - timedelta(seconds=settings.OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD)

    refresh_token_expiry_cutoff = now - timedelta(
        seconds=settings.OAUTH2_PROVIDER["REFRESH_TOKEN_EXPIRE_SECONDS"] + settings.OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD
    )

    context.log.info(f"Clearing OAuth tokens expired before {retention_cutoff}")

    token_operations = [
        {
            "model": OAuthRefreshToken,
            "queries": {
                "revoked": Q(revoked__lt=retention_cutoff),
                "expired_via_access_token": Q(access_token__expires__lt=refresh_token_expiry_cutoff),
            },
        },
        {
            "model": OAuthAccessToken,
            "queries": {
                "expired_standalone": Q(refresh_token__isnull=True, expires__lt=retention_cutoff),
            },
        },
        {
            "model": OAuthIDToken,
            "queries": {
                "expired_standalone": Q(access_token__isnull=True, expires__lt=retention_cutoff),
            },
        },
        {
            "model": OAuthGrant,
            "queries": {
                "expired": Q(expires__lt=retention_cutoff),
            },
        },
    ]

    total_deleted = 0
    for operation in token_operations:
        results = clear_expired_tokens_by_type(operation["model"], operation["queries"], context)
        total_deleted += sum(results.values())

    context.log.info(f"Total tokens deleted: {total_deleted}")

    context.add_output_metadata(
        {
            "total_tokens_deleted": dagster.MetadataValue.int(total_deleted),
            "retention_cutoff": dagster.MetadataValue.text(retention_cutoff.isoformat()),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def oauth_clear_expired_oauth_tokens_job():
    clear_expired_oauth_tokens()


oauth_clear_expired_oauth_tokens_schedule = dagster.ScheduleDefinition(
    job=oauth_clear_expired_oauth_tokens_job,
    cron_schedule="0 2 * * *",
    execution_timezone="UTC",
    name="oauth_cleanup_daily_schedule",
)
