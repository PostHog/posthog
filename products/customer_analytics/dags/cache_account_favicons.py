"""Caches a favicon for each customer analytics account logo domain on the static CDN, under the
same `favicons/<domain>` key as the web analytics favicon assets (`posthog/dags/common/favicons.py`), so `AccountLogo` can load it
without the logo.dev proxy and its budgets."""

import datetime as dt
from typing import cast

from django.utils import timezone

import dagster
from dagster_aws.s3 import S3Resource

from posthog.dags.common import JobOwners
from posthog.dags.common.favicons import CacheFaviconsConfig, download_and_cache_favicons, get_last_cached_domains

from products.customer_analytics.backend.logic.account_logo import list_logo_domains_across_teams

# Any user who can create accounts adds domains to this job, so bound the whole list and each
# team's share of it, and leave domains with no favicon alone for a week instead of every hour.
ACCOUNT_DOMAINS_LIMIT = 500_000
ACCOUNT_DOMAINS_PER_TEAM_LIMIT = 50_000
ACCOUNT_FAILED_DOMAIN_RETRY_AFTER = dt.timedelta(days=7)
# Stops starting new downloads before the next hourly run is due; the backlog continues next run.
ACCOUNT_FAVICONS_RUN_TIME_BUDGET = dt.timedelta(minutes=50)
# A run older than this is treated as stuck, so it does not block the schedule for ever.
ACCOUNT_FAVICONS_STUCK_RUN_AGE = dt.timedelta(hours=6)


def get_recently_failed_domains(
    context: dagster.AssetExecutionContext, asset_key: str, now: dt.datetime
) -> dict[str, str]:
    """Domains whose favicon download failed within the retry window, mapped to the failure date."""
    last_mat = context.instance.get_latest_materialization_event(dagster.AssetKey([asset_key]))
    if not last_mat or not last_mat.asset_materialization:
        return {}

    failed_meta = last_mat.asset_materialization.metadata.get("failed_domains")
    if not failed_meta or not isinstance(failed_meta, dagster.JsonMetadataValue):
        return {}
    retry_from = (now - ACCOUNT_FAILED_DOMAIN_RETRY_AFTER).date().isoformat()
    return {
        domain: failed_on
        for domain, failed_on in cast(dict[str, str], failed_meta.value).items()
        if failed_on > retry_from
    }


@dagster.asset
def cache_account_domain_favicons(
    context: dagster.AssetExecutionContext, s3: S3Resource, config: CacheFaviconsConfig
) -> dagster.MaterializeResult:
    context.log.info("Querying customer analytics account domains.")
    account_domains = list_logo_domains_across_teams(
        limit=ACCOUNT_DOMAINS_LIMIT, per_team_limit=ACCOUNT_DOMAINS_PER_TEAM_LIMIT
    )
    context.log.info(f"Found {len(account_domains)} account domains.")

    asset_key = "cache_account_domain_favicons"
    previously_cached = set() if config.force_refresh else get_last_cached_domains(context, asset_key)
    if previously_cached:
        context.log.info(f"Found {len(previously_cached)} previously cached domains.")
    now = timezone.now()
    recently_failed = {} if config.force_refresh else get_recently_failed_domains(context, asset_key, now)
    domains = [domain for domain in account_domains if domain not in recently_failed]

    run = download_and_cache_favicons(
        context, s3, domains, previously_cached, time_budget=ACCOUNT_FAVICONS_RUN_TIME_BUDGET
    )
    failed_domains = recently_failed | {domain: now.date().isoformat() for domain in run.failed_domains}

    context.log.info(
        f"Successfully cached {len(run.favicons)} new favicons, skipped {run.skipped_count} already cached, "
        f"{len(run.failed_domains)} failed, {len(recently_failed)} held back after a recent failure."
    )

    return dagster.MaterializeResult(
        metadata={
            "account_domains_queried": len(account_domains),
            "favicons_cached": len(run.favicons),
            "domains_skipped": run.skipped_count,
            "domains_failed": len(run.failed_domains),
            "domains_held_back": len(recently_failed),
            "out_of_time": run.out_of_time,
            "cached_domains": list(run.cached_domains),
            "failed_domains": failed_domains,
            "favicons": run.favicons,
        }
    )


cache_account_domain_favicons_job = dagster.define_asset_job(
    name="cache_account_domain_favicons_job",
    selection=["cache_account_domain_favicons"],
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="47 * * * *",  # Hourly; only domains not cached yet are downloaded
    job=cache_account_domain_favicons_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_ANALYTICS.value},
)
def cache_account_domain_favicons_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    active_runs = context.instance.get_runs(
        dagster.RunsFilter(
            job_name=cache_account_domain_favicons_job.name,
            statuses=[
                dagster.DagsterRunStatus.QUEUED,
                dagster.DagsterRunStatus.NOT_STARTED,
                dagster.DagsterRunStatus.STARTING,
                dagster.DagsterRunStatus.STARTED,
            ],
            created_after=timezone.now() - ACCOUNT_FAVICONS_STUCK_RUN_AGE,
        ),
        limit=1,
    )
    if active_runs:
        return dagster.SkipReason(f"Run {active_runs[0].run_id} is still queued or executing.")
    return dagster.RunRequest()
