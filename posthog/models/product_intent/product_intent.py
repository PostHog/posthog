from datetime import UTC, datetime

from celery import shared_task
from django.db import models

from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey
from posthog.models.insight import Insight
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel
from posthog.utils import get_instance_realm

"""
How to use this model:

Product intents are indicators that someone showed an interest in a given product.
They are triggered from the frontend when the user performs certain actions, like
selecting a product during onboarding or clicking on a certain button.

Some buttons that show product intent are frequently used by all users of the product,
so we need to know if it's a new product intent, or if it's just regular usage. We
can use the `activated_at` field to know if we should continue to update the product
intent row, or if we should stop because it's just regular usage.

The `activated_at` field is set by checking against certain criteria that differs for
each product. For instance, for the data warehouse product, we check if the user has
created any DataVisualizationNode insights in the 30 days after the product intent
was created. Each product needs to implement a method that checks for activation
criteria if the intent actions are the same as the general usage actions.

We shouldn't use this model and the `activated_at` field in place of sending events
about product usage because that limits our data exploration later. Definitely continue
sending events for product usage that we may want to track for any reason, along with
calculating activation here.

Note: single-event activation metrics that can also happen at the same time the intent
is created won't have tracking events sent for them. Unless you want to solve this,
make activation metrics require multiple things to happen.
"""


class ProductIntent(UUIDModel):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_type = models.CharField(max_length=255)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date the org completed activation for the product. Generally only used to know if we should continue updating the product_intent row.",
    )
    activation_last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date we last checked if the org had completed activation for the product.",
    )

    class Meta:
        unique_together = ["team", "product_type"]

    def __str__(self):
        return f"{self.team.name} - {self.product_type}"

    def has_activated_data_warehouse(self) -> bool:
        insights = Insight.objects.filter(
            team__project_id=self.team.project_id,
            created_at__gte=datetime(2024, 6, 1, tzinfo=UTC),
            query__kind="DataVisualizationNode",
        )

        excluded_tables = ["events", "persons", "sessions", "person_distinct_ids"]
        for insight in insights:
            if insight.query and insight.query.get("source", {}).get("query"):
                query_text = insight.query["source"]["query"].lower()
                # Check if query doesn't contain any of the excluded tables after 'from'
                has_excluded_table = any(f"from {table}" in query_text.replace("\\", "") for table in excluded_tables)
                if not has_excluded_table:
                    return True

        return False

    def has_activated_experiments(self) -> bool:
        # the team has any launched experiments
        return Experiment.objects.filter(team=self.team, start_date__isnull=False).exists()

    def has_activated_feature_flags(self) -> bool:
        # Get feature flags that have at least one filter group, excluding ones used by experiments and surveys
        experiment_flags = Experiment.objects.filter(team=self.team).values_list("feature_flag_id", flat=True)
        survey_flags = Survey.objects.filter(team=self.team).values_list("targeting_flag_id", flat=True)

        feature_flags = (
            FeatureFlag.objects.filter(
                team=self.team,
                filters__groups__0__properties__isnull=False,
            )
            .exclude(id__in=experiment_flags)
            .exclude(id__in=survey_flags)
            .only("id", "filters")
        )

        # To activate we need at least 2 feature flags
        if feature_flags.count() < 2:
            return False

        # To activate we need at least 2 filter groups across all flags
        total_groups = 0
        for flag in feature_flags:
            total_groups += len(flag.filters.get("groups", []))

        return total_groups >= 2

    def check_and_update_activation(self, skip_reporting: bool = False) -> bool:
        activation_checks = {
            "data_warehouse": self.has_activated_data_warehouse,
            "experiments": self.has_activated_experiments,
            "feature_flags": self.has_activated_feature_flags,
        }

        if self.product_type in activation_checks and activation_checks[self.product_type]():
            self.activated_at = datetime.now(tz=UTC)
            self.save()
            if not skip_reporting:
                self.report_activation(self.product_type)
            return True
        return False

    def report_activation(self, product_key: str) -> None:
        from posthog.event_usage import report_team_action

        report_team_action(
            self.team,
            "product intent marked activated",
            {
                "product_key": product_key,
                "intent_created_at": self.created_at,
                "intent_updated_at": self.updated_at,
                "realm": get_instance_realm(),
            },
        )


@shared_task(ignore_result=True)
def calculate_product_activation(team_id: int, only_calc_if_days_since_last_checked: int = 1) -> None:
    """
    Calculate product activation for a team.
    Only calculate if it's been more than `only_calc_if_days_since_last_checked` days since the last activation check.
    """
    team = Team.objects.get(id=team_id)
    product_intents = ProductIntent.objects.filter(team=team)
    for product_intent in product_intents:
        if product_intent.activated_at:
            continue
        if (
            product_intent.activation_last_checked_at
            and (datetime.now(tz=UTC) - product_intent.activation_last_checked_at).days
            <= only_calc_if_days_since_last_checked
        ):
            continue
        product_intent.check_and_update_activation()
