"""Bind the AE and CSM roles to relationship definitions and set the automated-claim controls for
one project. Binding names the role; it enrolls no account (see ``adopt_account_ownership``).

    python manage.py configure_account_ownership --team-id 2 --bind-ae <definition uuid>
    python manage.py configure_account_ownership --team-id 2 --claim-saved-query <view uuid> --claims enabled
"""

from typing import Any
from uuid import UUID

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.customer_analytics.backend.logic import ownership
from products.customer_analytics.backend.logic.ownership_claims import ClaimSourceMisconfigured, check_decision_columns
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig

# A zero allowance would accept a claim one microsecond past the fence, which no clock pair can promise.
MIN_CLOCK_SKEW_TOLERANCE_SECONDS = 1


class Command(BaseCommand):
    help = "Bind commercial roles to relationship definitions and control automated ownership claims."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        for role in ownership.OWNERSHIP_ROLES:
            group = parser.add_mutually_exclusive_group()
            group.add_argument(f"--bind-{role}", type=UUID, metavar="DEFINITION_ID")
            group.add_argument(f"--unbind-{role}", action="store_true")
        parser.add_argument("--claims", choices=["enabled", "disabled"])
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--claim-saved-query",
            type=UUID,
            metavar="SAVED_QUERY_ID",
            help="Warehouse view of Salesforce Task decisions the reconciler reads; see logic/ownership_claims.py.",
        )
        source.add_argument("--clear-claim-saved-query", action="store_true")
        parser.add_argument("--clock-skew-tolerance-seconds", type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")

        try:
            with transaction.atomic():
                for role in ownership.OWNERSHIP_ROLES:
                    if options[f"bind_{role}"] is not None or options[f"unbind_{role}"]:
                        ownership.bind_role(team, role, options[f"bind_{role}"])
        except ownership.InvalidRoleBindingError as error:
            raise CommandError(str(error))

        config = get_or_create_team_extension(team, TeamCustomerAnalyticsConfig)
        update_fields = []
        if options["claims"] is not None:
            config.ownership_claims_enabled = options["claims"] == "enabled"
            update_fields.append("ownership_claims_enabled")
        if options["claim_saved_query"] is not None:
            saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
            view = saved_query_model.objects.filter(
                team_id=team.id, id=options["claim_saved_query"], deleted=False
            ).first()
            if view is None:
                raise CommandError(f"No warehouse view {options['claim_saved_query']} in this project")
            try:
                check_decision_columns(view.name, view.columns)
            except ClaimSourceMisconfigured as error:
                raise CommandError(str(error))
            config.ownership_claim_saved_query = view
            update_fields.append("ownership_claim_saved_query")
        if options["clear_claim_saved_query"]:
            config.ownership_claim_saved_query = None
            update_fields.append("ownership_claim_saved_query")
        if options["clock_skew_tolerance_seconds"] is not None:
            if options["clock_skew_tolerance_seconds"] < MIN_CLOCK_SKEW_TOLERANCE_SECONDS:
                raise CommandError(
                    f"The clock-skew tolerance must be at least {MIN_CLOCK_SKEW_TOLERANCE_SECONDS} second(s)"
                )
            config.ownership_claim_clock_skew_tolerance_seconds = options["clock_skew_tolerance_seconds"]
            update_fields.append("ownership_claim_clock_skew_tolerance_seconds")
        if update_fields:
            config.save(update_fields=update_fields)

        bindings = ownership.role_bindings(team.id)
        config.refresh_from_db()
        self.stdout.write(
            f"team {team.id}: ae={bindings.ae_definition_id} csm={bindings.csm_definition_id} "
            f"claims={'enabled' if config.ownership_claims_enabled else 'disabled'} "
            f"claim_saved_query={config.ownership_claim_saved_query_id or '<unset>'} "
            f"clock_skew_tolerance_seconds={config.ownership_claim_clock_skew_tolerance_seconds}"
        )
