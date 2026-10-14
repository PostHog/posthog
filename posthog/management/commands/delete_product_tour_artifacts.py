from collections import Counter
from collections.abc import Iterator
from typing import Any, TypeVar

from django.core.management.base import BaseCommand, CommandParser
from django.db import models, transaction

from rest_framework.exceptions import ValidationError

from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.api.survey import delete_survey_flags_and_log
from products.surveys.backend.models import Survey

ModelT = TypeVar("ModelT", bound=models.Model)


def _batches(queryset: "models.QuerySet[ModelT]", batch_size: int) -> Iterator[list[ModelT]]:
    last_pk: Any = None
    while True:
        page = queryset.order_by("pk")
        if last_pk is not None:
            page = page.filter(pk__gt=last_pk)
        batch = list(page[:batch_size])
        if not batch:
            return
        yield batch
        last_pk = batch[-1].pk


def tour_targeting_flags() -> "models.QuerySet[FeatureFlag]":
    # Only the flags tours created for themselves. A tour's linked_flag belongs to the customer.
    tour_flag_ids = ProductTour.objects.filter(internal_targeting_flag__isnull=False).values(
        "internal_targeting_flag_id"
    )
    return FeatureFlag.objects.filter(id__in=tour_flag_ids, deleted=False).select_related("team")


def tour_surveys() -> "models.QuerySet[Survey]":
    tour_survey_ids = Survey.objects.filter(product_tour__isnull=False).values("id")
    return Survey.objects.filter(id__in=tour_survey_ids).select_related(
        "team", "targeting_flag", "internal_targeting_flag"
    )


class Command(BaseCommand):
    help = (
        "Delete the feature flags and surveys that product tours created for themselves: each tour's internal "
        "targeting flag, and each survey linked to a tour with that survey's own targeting flags. A tour's "
        "linked flag is left alone. It reads the product tour tables to find them, so run it after the deploy "
        "that retires product tours and before the migration that drops those tables. Dry run unless --live."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live", action="store_true", help="Delete the artifacts. Without it, only report counts.")
        parser.add_argument("--batch-size", type=int, default=200, help="Rows to load per batch.")

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live"]
        batch_size: int = options["batch_size"]
        flags: Counter[int] = Counter()
        surveys: Counter[int] = Counter()
        skipped: list[str] = []

        for flag_batch in _batches(tour_targeting_flags(), batch_size):
            for flag in flag_batch:
                if live:
                    try:
                        # A system write through the flag serializer, the path the API's soft delete takes.
                        update_flag(flag, {"deleted": True, "active": False}, team=flag.team, user=None)
                    except ValidationError as error:
                        skipped.append(f"flag {flag.id} (team {flag.team_id}): {error.detail}")
                        continue
                flags[flag.team_id] += 1

        for survey_batch in _batches(tour_surveys(), batch_size):
            for survey in survey_batch:
                if live:
                    with transaction.atomic():
                        delete_survey_flags_and_log(
                            survey,
                            organization_id=survey.team.organization_id,
                            team_id=survey.team_id,
                            user=None,
                            was_impersonated=False,
                        )
                        survey.delete()
                surveys[survey.team_id] += 1

        verb = "Deleted" if live else "Would delete"
        for team_id in sorted(flags.keys() | surveys.keys()):
            self.stdout.write(f"team {team_id}: {verb.lower()} {flags[team_id]} flags, {surveys[team_id]} surveys")
        self.stdout.write(f"{verb} {sum(flags.values())} flags and {sum(surveys.values())} surveys in total")
        for line in skipped:
            self.stdout.write(f"Skipped {line}")
        if not live:
            self.stdout.write("Dry run. Pass --live to delete.")
