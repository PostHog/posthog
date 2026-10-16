"""Marketing analytics project settings schemas."""

from typing import Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction

from drf_spectacular.utils import extend_schema_field
from pydantic import RootModel as PydanticRootModel
from pydantic.json_schema import SkipJsonSchema
from rest_framework import serializers

from posthog.schema import (
    AttributionMode,
    CampaignFieldPreference,
    CohortPropertyFilter,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EventPropertyFilter,
    HogQLPropertyFilter,
    MarketingAnalyticsOverviewMetric as OverviewMetric,
    PersonPropertyFilter,
    SourceMap,
)

from posthog.models import TeamMarketingAnalyticsConfig
from posthog.models.team.team_marketing_analytics_config import (
    validate_overview_metrics as validate_overview_metrics_list,
)

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin

# The filters a conversion goal can carry, rather than every filter HogQL knows about. The goal
# runtime resolves these through `property_to_expr` with an event scope, where `revenue_analytics`
# and `account_custom_property` raise and `metric_attribute` is unimplemented, and the goal editor
# only offers these six. Narrowing here follows `WebAnalyticsPropertyFilter`.
MarketingAnalyticsConversionGoalPropertyFilter = (
    EventPropertyFilter
    | PersonPropertyFilter
    | CohortPropertyFilter
    | ElementPropertyFilter
    | HogQLPropertyFilter
    | DataWarehousePropertyFilter
)


class MarketingAnalyticsOverviewMetricChoices(models.TextChoices):
    VISITORS = OverviewMetric.VISITORS.value, OverviewMetric.VISITORS.value
    NEW_VISITORS = OverviewMetric.NEW_VISITORS.value, OverviewMetric.NEW_VISITORS.value
    NEW_VISITOR_SHARE = OverviewMetric.NEW_VISITOR_SHARE.value, OverviewMetric.NEW_VISITOR_SHARE.value
    SESSIONS = OverviewMetric.SESSIONS.value, OverviewMetric.SESSIONS.value
    PAGEVIEWS = OverviewMetric.PAGEVIEWS.value, OverviewMetric.PAGEVIEWS.value
    SESSION_DURATION = OverviewMetric.SESSION_DURATION.value, OverviewMetric.SESSION_DURATION.value
    PAGES_PER_SESSION = OverviewMetric.PAGES_PER_SESSION.value, OverviewMetric.PAGES_PER_SESSION.value
    PAGES_PER_VISITOR = OverviewMetric.PAGES_PER_VISITOR.value, OverviewMetric.PAGES_PER_VISITOR.value
    SESSIONS_PER_VISITOR = OverviewMetric.SESSIONS_PER_VISITOR.value, OverviewMetric.SESSIONS_PER_VISITOR.value
    BOUNCE_RATE = OverviewMetric.BOUNCE_RATE.value, OverviewMetric.BOUNCE_RATE.value
    RETURNING_VISITORS = OverviewMetric.RETURNING_VISITORS.value, OverviewMetric.RETURNING_VISITORS.value
    RETURN_RATE_7D = OverviewMetric.RETURN_RATE_7D.value, OverviewMetric.RETURN_RATE_7D.value
    RETURN_RATE_30D = OverviewMetric.RETURN_RATE_30D.value, OverviewMetric.RETURN_RATE_30D.value
    MEDIAN_RETURN_DAYS = OverviewMetric.MEDIAN_RETURN_DAYS.value, OverviewMetric.MEDIAN_RETURN_DAYS.value
    CONVERSIONS = OverviewMetric.CONVERSIONS.value, OverviewMetric.CONVERSIONS.value
    CONVERSION_RATE = OverviewMetric.CONVERSION_RATE.value, OverviewMetric.CONVERSION_RATE.value
    CONVERSION_VALUE = OverviewMetric.CONVERSION_VALUE.value, OverviewMetric.CONVERSION_VALUE.value
    AVG_CONVERSION_VALUE = OverviewMetric.AVG_CONVERSION_VALUE.value, OverviewMetric.AVG_CONVERSION_VALUE.value
    REVENUE = OverviewMetric.REVENUE.value, OverviewMetric.REVENUE.value


# Subclassing the canonical goal schemas rather than redeclaring their ~25 fields keeps this write
# surface from drifting when the query schema changes. The cost is that narrowing a field's type in
# a subclass is not assignment-compatible, hence the ignores below: each one marks a deliberate
# divergence from the query schema, not an oversight.
#
# `fixedProperties` stays accepted but leaves the documented schema: nothing in the marketing
# analytics runtime reads it, and advertising it costs a third of this field's generated schema.
class MarketingAnalyticsEventConversionGoal(ConversionGoalFilter1):
    """A conversion goal counted from events."""

    # `validate_conversion_goals` rejects a goal without a string name or an explicit kind, so the
    # documented schema has to require both. `conversion_goal_id` stays required like the query
    # schema: nothing here assigns one, and a goal stored without it fails to rebuild for queries.
    kind: Literal["EventsNode"]
    name: str
    properties: list[MarketingAnalyticsConversionGoalPropertyFilter] | None = None  # type: ignore[assignment]
    fixedProperties: SkipJsonSchema[list[MarketingAnalyticsConversionGoalPropertyFilter] | None] = None  # type: ignore[assignment]


class MarketingAnalyticsActionConversionGoal(ConversionGoalFilter2):
    """A conversion goal counted from an action."""

    kind: Literal["ActionsNode"]
    name: str
    properties: list[MarketingAnalyticsConversionGoalPropertyFilter] | None = None  # type: ignore[assignment]
    fixedProperties: SkipJsonSchema[list[MarketingAnalyticsConversionGoalPropertyFilter] | None] = None  # type: ignore[assignment]


class MarketingAnalyticsWarehouseConversionGoal(ConversionGoalFilter3):
    """A conversion goal counted from a data warehouse table."""

    kind: Literal["DataWarehouseNode"]
    name: str
    properties: list[MarketingAnalyticsConversionGoalPropertyFilter] | None = None  # type: ignore[assignment]
    fixedProperties: SkipJsonSchema[list[MarketingAnalyticsConversionGoalPropertyFilter] | None] = None  # type: ignore[assignment]


class MarketingAnalyticsConversionGoalList(PydanticRootModel):
    """The conversion goals configured for marketing analytics, in display order."""

    root: list[
        MarketingAnalyticsEventConversionGoal
        | MarketingAnalyticsActionConversionGoal
        | MarketingAnalyticsWarehouseConversionGoal
    ]


class MarketingAnalyticsSourceMapping(PydanticRootModel):
    """Mapping of external data source id to that source's column mapping."""

    root: dict[str, SourceMap]


class MarketingAnalyticsCampaignFieldPreferences(PydanticRootModel):
    """Mapping of integration type to the campaign field used when matching campaigns."""

    root: dict[str, CampaignFieldPreference]


class MarketingAnalyticsCampaignNameMappings(PydanticRootModel):
    """Mapping of integration type to canonical campaign name to the aliases folded into it."""

    root: dict[str, dict[str, list[str]]]


class MarketingAnalyticsCustomSourceMappings(PydanticRootModel):
    """Mapping of integration type to the custom UTM source values folded into it."""

    root: dict[str, list[str]]


@extend_schema_field(MarketingAnalyticsCampaignNameMappings)  # type: ignore[arg-type]
class MarketingAnalyticsCampaignNameMappingsField(serializers.JSONField):
    pass


@extend_schema_field(MarketingAnalyticsCustomSourceMappings)  # type: ignore[arg-type]
class MarketingAnalyticsCustomSourceMappingsField(serializers.JSONField):
    pass


@extend_schema_field(MarketingAnalyticsConversionGoalList)  # type: ignore[arg-type]
class MarketingAnalyticsConversionGoalsField(serializers.JSONField):
    pass


@extend_schema_field(MarketingAnalyticsSourceMapping)  # type: ignore[arg-type]
class MarketingAnalyticsSourcesMapField(serializers.JSONField):
    pass


@extend_schema_field(MarketingAnalyticsCampaignFieldPreferences)  # type: ignore[arg-type]
class MarketingAnalyticsCampaignFieldPreferencesField(serializers.JSONField):
    pass


class TeamMarketingAnalyticsConfigSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    sources_map = MarketingAnalyticsSourcesMapField(
        required=False,
        help_text=(
            "Column mapping per external data source, keyed by source id. Tells marketing analytics which column "
            "holds campaign, source, cost, clicks and impressions for that source."
        ),
    )
    conversion_goals = MarketingAnalyticsConversionGoalsField(
        required=False,
        help_text=(
            "Conversion goals to attribute against, in display order. Each goal points at an event, an action or a "
            "data warehouse table, and carries a schema_map describing which fields hold the UTM parameters, the "
            "timestamp and the distinct id. Replaces the whole list on write."
        ),
    )
    attribution_window_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=90,
        help_text="How many days back a touchpoint can be credited for a conversion. Between 1 and 90.",
    )
    # nosemgrep: choices-need-a-class -- an existing list, moved here unchanged from posthog/api/team.py
    attribution_mode = serializers.ChoiceField(
        choices=[(mode.value, mode.value.replace("_", " ").title()) for mode in AttributionMode],
        required=False,
        help_text="How credit is split across touchpoints when a person saw several campaigns before converting.",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether marketing analytics drops traffic matching the project's test-account filters. Off by default."
        ),
    )
    campaign_name_mappings = MarketingAnalyticsCampaignNameMappingsField(
        required=False,
        help_text=(
            "Manual campaign name aliases, keyed by integration type then by canonical campaign name, with the list "
            "of names that should be folded into it. Applied before automatic matching."
        ),
    )
    custom_source_mappings = MarketingAnalyticsCustomSourceMappingsField(
        required=False,
        help_text=(
            "Custom UTM source values to fold into an integration, keyed by integration type. A UTM source can only "
            "belong to one integration."
        ),
    )
    campaign_field_preferences = MarketingAnalyticsCampaignFieldPreferencesField(
        required=False,
        help_text=(
            "Which field to match campaigns on per integration type, campaign_name or campaign_id. Manual mappings "
            "in campaign_name_mappings still take precedence."
        ),
    )
    overview_metrics = serializers.ListField(
        child=serializers.ChoiceField(choices=MarketingAnalyticsOverviewMetricChoices.choices),
        required=False,
        allow_empty=True,
        help_text=(
            "Metric cards the marketing analytics Overview shows: exactly five, one per slot, in the order "
            "acquisition, engagement, retention, conversion, other. A metric may repeat, because the other slot can "
            "hold one another slot already shows. Send an empty list to restore the default. Reads always return the "
            "effective list."
        ),
    )

    class Meta:
        model = TeamMarketingAnalyticsConfig
        fields = [
            "sources_map",
            "conversion_goals",
            "attribution_window_days",
            "attribution_mode",
            "filter_test_accounts",
            "campaign_name_mappings",
            "custom_source_mappings",
            "campaign_field_preferences",
            "overview_metrics",
        ]

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)
        if "sources_map" in internal_value:
            internal_value["_sources_map"] = internal_value["sources_map"]
        if "conversion_goals" in internal_value:
            internal_value["_conversion_goals"] = internal_value["conversion_goals"]
        if "campaign_name_mappings" in internal_value:
            internal_value["_campaign_name_mappings"] = internal_value["campaign_name_mappings"]
        if "custom_source_mappings" in internal_value:
            internal_value["_custom_source_mappings"] = internal_value["custom_source_mappings"]
        if "campaign_field_preferences" in internal_value:
            internal_value["_campaign_field_preferences"] = internal_value["campaign_field_preferences"]
        if "overview_metrics" in internal_value:
            internal_value["_overview_metrics"] = internal_value["overview_metrics"]
        return internal_value

    def validate_overview_metrics(self, value: list[str]) -> list[str]:
        # ChoiceField already rejects unknown keys; this adds the duplicate check as a 400 rather
        # than a 500 from the model setter.
        try:
            validate_overview_metrics_list(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        instance.refresh_from_db(from_queryset=TeamMarketingAnalyticsConfig.objects.select_for_update())
        # Handle sources_map with partial updates
        if "sources_map" in validated_data:
            new_sources_map = validated_data["sources_map"]

            # For each source in the new data, update it individually
            for source_id, field_mapping in new_sources_map.items():
                if field_mapping is None:
                    # If None is passed, remove the source entirely
                    instance.remove_source_mapping(source_id)
                else:
                    # Update the source mapping (this preserves other sources)
                    instance.update_source_mapping(source_id, field_mapping)

        if "conversion_goals" in validated_data:
            instance.conversion_goals = validated_data["conversion_goals"]

        # Handle attribution settings
        if "attribution_window_days" in validated_data:
            instance.attribution_window_days = validated_data["attribution_window_days"]

        if "attribution_mode" in validated_data:
            instance.attribution_mode = validated_data["attribution_mode"]

        if "filter_test_accounts" in validated_data:
            instance.filter_test_accounts = validated_data["filter_test_accounts"]

        if "campaign_name_mappings" in validated_data:
            instance.campaign_name_mappings = validated_data["campaign_name_mappings"]

        if "custom_source_mappings" in validated_data:
            instance.custom_source_mappings = validated_data["custom_source_mappings"]

        if "campaign_field_preferences" in validated_data:
            instance.campaign_field_preferences = validated_data["campaign_field_preferences"]

        if "overview_metrics" in validated_data:
            instance.overview_metrics = validated_data["overview_metrics"]

        instance.save()
        return instance
