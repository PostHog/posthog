"""Choose which relationship definitions customer analytics may control and which warehouse view of
external decisions fills each of them. Taking control of a definition enrolls no account at once.
From then on, a person's change to a controlled relationship on a linked account enrolls that
account under every controlled definition. ``adopt_account_ownership`` enrolls accounts in reviewed
batches. No path unenrolls an account, so control cannot end after the first enrollment.

    python manage.py configure_account_ownership --team-id 2 --control <definition uuid>
    python manage.py configure_account_ownership --team-id 2 --claim-view <definition uuid> <view uuid> \\
        --claims <definition uuid> enabled
"""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Q

from posthog.models.team import Team

from products.customer_analytics.backend.logic import ownership, ownership_claims
from products.customer_analytics.backend.models import AccountRelationshipDefinition


class Command(BaseCommand):
    help = "Choose the controlled relationship definitions of a project and the claim view each one reads."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--control",
            type=UUID,
            action="append",
            default=[],
            metavar="DEFINITION_ID",
            help=(
                "Let customer analytics take control of this single-holder definition per account. A person's "
                "change to a controlled relationship on a linked account then enrolls that account under every "
                "controlled definition. --uncontrol is refused once any account is enrolled. Repeatable."
            ),
        )
        parser.add_argument(
            "--uncontrol",
            type=UUID,
            action="append",
            default=[],
            metavar="DEFINITION_ID",
            help="Stop controlling this definition; refused while any account is enrolled under it. Repeatable.",
        )
        parser.add_argument(
            "--claim-view",
            nargs=2,
            action="append",
            default=[],
            metavar=("DEFINITION_ID", "SAVED_QUERY_ID"),
            help=(
                "Bind the warehouse view of decisions that fill this controlled definition; see "
                "logic/ownership_claims.py. Repeatable."
            ),
        )
        parser.add_argument(
            "--clear-claim-view",
            type=UUID,
            action="append",
            default=[],
            metavar="DEFINITION_ID",
            help="Unbind the definition's claim view, which also switches its sweep off. Repeatable.",
        )
        parser.add_argument(
            "--claims",
            nargs=2,
            action="append",
            default=[],
            metavar=("DEFINITION_ID", "enabled|disabled"),
            help="Switch the sweep on or off for this definition's view. Repeatable.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")
        claim_views = self._one_per_definition(
            [(self._uuid(definition_id), self._uuid(view_id)) for definition_id, view_id in options["claim_view"]],
            "--claim-view",
        )
        switches = self._one_per_definition(
            [(self._uuid(definition_id), self._switch(state)) for definition_id, state in options["claims"]], "--claims"
        )
        contradicted = set(options["clear_claim_view"]) & {definition_id for definition_id, _ in claim_views}
        if contradicted:
            raise CommandError(
                f"--claim-view and --clear-claim-view both name {', '.join(str(d) for d in sorted(contradicted))}"
            )

        # One transaction, so a refused change leaves the configuration as it was. Every definition
        # the call touches is locked first, by id, so two concurrent calls take their locks in one
        # order. Control starts before views are bound and ends after they are cleared, so one call
        # can move a view from one definition to another.
        try:
            with transaction.atomic():
                referenced = {
                    *options["control"],
                    *options["uncontrol"],
                    *options["clear_claim_view"],
                    *(definition_id for definition_id, _ in claim_views),
                    *(definition_id for definition_id, _ in switches),
                }
                ownership.lock_definitions(team.id, sorted(referenced))
                for definition_id in options["control"]:
                    ownership.set_controlled(team.id, definition_id, True)
                for definition_id in options["clear_claim_view"]:
                    ownership_claims.bind_claim_view(team.id, definition_id, None)
                for definition_id, view_id in claim_views:
                    ownership_claims.bind_claim_view(team.id, definition_id, view_id)
                for definition_id, enabled in switches:
                    ownership_claims.set_claims_enabled(team.id, definition_id, enabled)
                for definition_id in options["uncontrol"]:
                    ownership.set_controlled(team.id, definition_id, False)
        except (ownership.InvalidControlChangeError, ownership_claims.ClaimSourceMisconfigured) as error:
            raise CommandError(str(error))

        # Every definition with any ownership state, so nothing controlled or bound goes unlisted.
        listed = (
            AccountRelationshipDefinition.objects.for_team(team.id)
            .filter(Q(is_controlled=True) | Q(claims_enabled=True) | Q(claim_saved_query__isnull=False))
            .order_by("name")
        )
        for definition in listed:
            self.stdout.write(
                f"team {team.id}: {definition.name} ({definition.id}) "
                f"controlled={'yes' if definition.is_controlled else 'no'} "
                f"claims={'enabled' if definition.claims_enabled else 'disabled'} "
                f"claim_view={definition.claim_saved_query_id or '<unset>'}"
            )

    @staticmethod
    def _one_per_definition(pairs: list[tuple[UUID, Any]], flag: str) -> list[tuple[UUID, Any]]:
        """Refuse a definition named twice with different values, which would otherwise resolve by order."""
        seen: dict[UUID, Any] = {}
        for definition_id, value in pairs:
            if definition_id in seen and seen[definition_id] != value:
                raise CommandError(f"{flag} names {definition_id} twice with different values")
            seen[definition_id] = value
        return list(seen.items())

    @staticmethod
    def _uuid(value: str) -> UUID:
        try:
            return UUID(value)
        except ValueError:
            raise CommandError(f"{value} is not a UUID")

    @staticmethod
    def _switch(value: str) -> bool:
        if value not in ("enabled", "disabled"):
            raise CommandError(f"--claims takes enabled or disabled, not {value}")
        return value == "enabled"
