"""Choose which relationship definitions customer analytics may control and set the Salesforce claim
controls for one project. Taking control of a definition enrolls no account (see
``adopt_account_ownership``).

    python manage.py configure_account_ownership --team-id 2 --control <definition uuid>
    python manage.py configure_account_ownership --team-id 2 --claim-definition <definition uuid> \\
        --claim-saved-query <view uuid> --claims enabled
"""

from typing import Any
from uuid import UUID

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.customer_analytics.backend.constants import DEFAULT_ACTIVITY_EVENT
from products.customer_analytics.backend.logic import ownership
from products.customer_analytics.backend.logic.ownership_claims import ClaimSourceMisconfigured, check_decision_columns
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig


class Command(BaseCommand):
    help = "Choose the controlled relationship definitions and the automated ownership claim controls of a project."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--control",
            type=UUID,
            action="append",
            default=[],
            metavar="DEFINITION_ID",
            help="Let customer analytics take control of this single-holder definition per account. Repeatable.",
        )
        parser.add_argument(
            "--uncontrol",
            type=UUID,
            action="append",
            default=[],
            metavar="DEFINITION_ID",
            help="Stop controlling this definition; refused while any account is enrolled under it. Repeatable.",
        )
        target = parser.add_mutually_exclusive_group()
        target.add_argument(
            "--claim-definition",
            type=UUID,
            metavar="DEFINITION_ID",
            help="The controlled definition a Salesforce Task allocation fills.",
        )
        target.add_argument("--clear-claim-definition", action="store_true")
        parser.add_argument("--claims", choices=["enabled", "disabled"])
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--claim-saved-query",
            type=UUID,
            metavar="SAVED_QUERY_ID",
            help="Warehouse view of Salesforce Task decisions the reconciler reads; see logic/ownership_claims.py.",
        )
        source.add_argument("--clear-claim-saved-query", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")

        # One transaction, so a refused control change or an unusable view leaves the configuration
        # as it was. Control starts before the claim target is set and ends after it is cleared, so
        # one call can move the target from one definition to another.
        try:
            with transaction.atomic():
                # Every definition this call touches is locked first, by id, so two concurrent calls
                # take their locks in one order and neither waits on the other's config row.
                touched = {*options["control"], *options["uncontrol"]}
                if options["claim_definition"] is not None:
                    touched.add(options["claim_definition"])
                for definition_id in sorted(touched):
                    ownership.lock_definition(team.id, definition_id)
                for definition_id in options["control"]:
                    ownership.set_controlled(team.id, definition_id, True)
                config = get_or_create_team_extension(
                    team, TeamCustomerAnalyticsConfig, defaults={"activity_event": DEFAULT_ACTIVITY_EVENT}
                )
                update_fields = []
                if options["claim_definition"] is not None:
                    definition = ownership.lock_definition(team.id, options["claim_definition"])
                    if definition is None:
                        raise CommandError(f"No relationship definition {options['claim_definition']} in this project")
                    if not definition.is_controlled:
                        raise CommandError(
                            f"{definition.name} is not controlled; a claim can only fill a controlled relationship"
                        )
                    config.ownership_claim_relationship_definition = definition
                    update_fields.append("ownership_claim_relationship_definition")
                if options["clear_claim_definition"]:
                    config.ownership_claim_relationship_definition = None
                    update_fields.append("ownership_claim_relationship_definition")
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
                    check_decision_columns(view.name, view.columns)
                    config.ownership_claim_saved_query = view
                    update_fields.append("ownership_claim_saved_query")
                if options["clear_claim_saved_query"]:
                    config.ownership_claim_saved_query = None
                    update_fields.append("ownership_claim_saved_query")
                if update_fields:
                    config.save(update_fields=update_fields)
                for definition_id in options["uncontrol"]:
                    ownership.set_controlled(team.id, definition_id, False)
        except (ownership.InvalidControlChangeError, ClaimSourceMisconfigured) as error:
            raise CommandError(str(error))

        config.refresh_from_db()
        controlled = ", ".join(
            f"{definition.name} ({definition.id})" for definition in ownership.controlled_definitions(team.id)
        )
        self.stdout.write(
            f"team {team.id}: controlled=[{controlled}] "
            f"claim_definition={config.ownership_claim_relationship_definition_id or '<unset>'} "
            f"claims={'enabled' if config.ownership_claims_enabled else 'disabled'} "
            f"claim_saved_query={config.ownership_claim_saved_query_id or '<unset>'}"
        )
