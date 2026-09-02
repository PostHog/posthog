import json
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync

from posthog.models import Organization, Team
from posthog.redis import get_client

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination
from products.batch_exports.backend.temporal.batch_exports import check_is_over_limit

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

# Destinations excluded from rows exported billing, and thus from the billing check.
NON_BILLABLE_DESTINATIONS = [
    BatchExportDestination.Destination.HTTP,
    BatchExportDestination.Destination.WORKFLOWS,
]


class Command(BaseCommand):
    help = (
        "Check which teams would have their batch exports fail due to being over "
        "the rows exported billing limit. Runs the same check batch export workflows run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Check a single team")
        parser.add_argument("--organization-id", default=None, type=str, help="Check all teams in an organization")
        parser.add_argument(
            "--json", action="store_true", dest="as_json", help="Output machine-readable JSON, one object per line"
        )

    def handle(self, **options):
        team_id = options["team_id"]
        organization_id = options["organization_id"]
        as_json = options["as_json"]

        checked = False
        if team_id is not None:
            teams = [Team.objects.select_related("organization").get(id=team_id)]
        elif organization_id is not None:
            try:
                organization = Organization.objects.get(id=organization_id)
            except Organization.DoesNotExist:
                raise CommandError(f"Organization '{organization_id}' not found")
            teams = list(Team.objects.select_related("organization").filter(organization=organization))
        else:
            teams = self._teams_with_limited_billable_exports()
            checked = True

        for team in teams:
            self._report_team(team, as_json, checked)

        if not teams:
            self.stdout.write("No teams with active billable batch exports are over the billing limit.")

    def _teams_with_limited_billable_exports(self) -> list[Team]:
        """Return teams in the quota-limit zset that have active billable batch exports."""
        limited_tokens = list_limited_team_attributes(
            QuotaResource.ROWS_EXPORTED,
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            use_cache=False,
        )
        return list(
            Team.objects.select_related("organization")
            .filter(
                api_token__in=limited_tokens,
                batchexport__deleted=False,
                batchexport__paused=False,
            )
            .exclude(batchexport__destination__type__in=NON_BILLABLE_DESTINATIONS)
            .distinct()
        )

    def _report_team(self, team: Team, as_json: bool, checked: bool) -> None:
        if not checked:
            is_over_limit = async_to_sync(check_is_over_limit)(team.id)
        else:
            is_over_limit = True

        zset_key = f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}{QuotaResource.ROWS_EXPORTED.value}"
        score = get_client().zscore(zset_key, team.api_token)
        limited_until = dt.datetime.fromtimestamp(score, tz=dt.UTC).isoformat() if score else None

        usage_summary = (team.organization.usage or {}).get(QuotaResource.ROWS_EXPORTED.value) or {}
        trust_scores = team.organization.customer_trust_scores or {}

        active_exports = (
            BatchExport.objects.filter(team_id=team.id, deleted=False, paused=False)
            .exclude(destination__type__in=NON_BILLABLE_DESTINATIONS)
            .values_list("destination__type", flat=True)
        )

        report = {
            "team_id": team.id,
            "organization_id": str(team.organization_id),
            "over_billing_limit": is_over_limit,
            "limited_until": limited_until,
            "usage": usage_summary.get("usage"),
            "todays_usage": usage_summary.get("todays_usage"),
            "limit": usage_summary.get("limit"),
            "trust_score": trust_scores.get(QuotaResource.ROWS_EXPORTED.value),
            "never_drop_data": team.organization.never_drop_data,
            "active_billable_exports": sorted(active_exports),
        }

        if as_json:
            self.stdout.write(json.dumps(report))
            return

        status = self.style.ERROR("OVER LIMIT") if is_over_limit else self.style.SUCCESS("ok")
        self.stdout.write(
            f"team={report['team_id']} org={report['organization_id']} {status} "
            f"usage={report['usage']} todays_usage={report['todays_usage']} limit={report['limit']} "
            f"trust_score={report['trust_score']} limited_until={report['limited_until']} "
            f"never_drop_data={report['never_drop_data']} "
            f"active_billable_exports={report['active_billable_exports']}"
        )
