import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from pydantic_core import ValidationError as PydanticValidationError

from posthog.schema import TestAccountFilters

from posthog.models import Team


class Command(BaseCommand):
    help = "Audit Team.test_account_filters values against the generated TestAccountFilters schema"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            dest="team_ids",
            action="append",
            type=int,
            help="Team ID to audit. Can be provided multiple times. Defaults to all teams with non-empty filters.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of teams to audit.",
        )
        parser.add_argument(
            "--format",
            choices=["text", "jsonl"],
            default="text",
            help="Output format for invalid teams.",
        )
        parser.add_argument(
            "--fail-on-invalid",
            action="store_true",
            help="Exit with a non-zero status if any invalid filters are found.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids: list[int] | None = options.get("team_ids")
        limit: int | None = options.get("limit")
        output_format: str = options["format"]
        fail_on_invalid: bool = options["fail_on_invalid"]

        queryset = Team.objects.only("id", "organization_id", "project_id", "test_account_filters").order_by("id")
        if team_ids:
            queryset = queryset.filter(id__in=team_ids)
        else:
            queryset = queryset.exclude(test_account_filters=[])

        if limit is not None:
            if limit < 1:
                raise CommandError("--limit must be greater than 0.")
            queryset = queryset[:limit]

        checked_count = 0
        invalid_count = 0

        for team in queryset.iterator(chunk_size=500):
            checked_count += 1
            try:
                TestAccountFilters.model_validate(team.test_account_filters)
            except PydanticValidationError as error:
                invalid_count += 1
                self._write_invalid_team(team, error, output_format)

        summary = f"Audited {checked_count} team(s): {invalid_count} invalid, {checked_count - invalid_count} valid."
        if invalid_count:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

        if fail_on_invalid and invalid_count:
            raise CommandError(f"Found {invalid_count} team(s) with invalid test account filters.")

    def _write_invalid_team(self, team: Team, error: PydanticValidationError, output_format: str) -> None:
        errors = error.errors(include_url=False)
        if output_format == "jsonl":
            self.stdout.write(
                json.dumps(
                    {
                        "team_id": team.id,
                        "project_id": team.project_id,
                        "organization_id": str(team.organization_id),
                        "errors": errors,
                        "test_account_filters": team.test_account_filters,
                    },
                    default=str,
                )
            )
            return

        first_error_message = errors[0].get("msg", "validation failed") if errors else "validation failed"
        self.stdout.write(
            self.style.WARNING(
                "Invalid test account filters for "
                f"team_id={team.id}, project_id={team.project_id}, organization_id={team.organization_id}: "
                f"{first_error_message}"
            )
        )
