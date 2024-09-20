import json
from typing import get_args

from rest_framework import serializers

from posthog.api.documentation import (
    FilterActionSerializer,
    FilterEventSerializer,
    OpenApiTypes,
    PropertySerializer,
    extend_schema_field,
    property_help_text,
)
from posthog.constants import (
    ACTIONS,
    BREAKDOWN_TYPES,
    DISPLAY_TYPES,
    EVENTS,
    FUNNEL_WINDOW_INTERVAL_TYPES,
    PROPERTIES,
    FunnelOrderType,
    FunnelVizType,
)
from posthog.models.team import TIMEZONES


class GenericInsightsSerializer(serializers.Serializer):
    def __init__(self, request=None, *args, **kwargs):
        if request:
            data = {**request.data, **request.GET.dict()}
            if data.get(ACTIONS):
                actions = data.get(ACTIONS, [])
                if isinstance(actions, str):
                    actions = json.loads(actions)
                data["actions"] = actions
            if data.get(EVENTS):
                events = data.get(EVENTS, [])
                if isinstance(events, str):
                    events = json.loads(events)
                data["events"] = events
            if data.get(PROPERTIES):
                properties = data.get(PROPERTIES, [])
                if isinstance(properties, str):
                    properties = json.loads(properties)
                data["properties"] = properties
            kwargs["data"] = data

        super().__init__(*args, **kwargs)

    events = FilterEventSerializer(
        required=False,
        many=True,
        help_text="Events to filter on. One of `events` or `actions` is required.",
    )
    actions = FilterActionSerializer(
        required=False,
        many=True,
        help_text="Actions to filter on. One of `events` or `actions` is required.",
    )
    properties = PropertySerializer(required=False, help_text=property_help_text)
    filter_test_accounts = serializers.BooleanField(
        help_text='Whether to filter out internal and test accounts. See "project settings" in your PostHog account for the filters.',
        default=False,
    )
    date_from = serializers.CharField(
        required=False,
        help_text="What date to filter the results from. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.",
        default="-7d",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="What date to filter the results to. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.",
        default="-7d",
    )


@extend_schema_field(OpenApiTypes.STR)
class BreakdownField(serializers.Field):
    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        return data


class BreakdownMixin(serializers.Serializer):
    breakdown = BreakdownField(
        required=False,
        help_text="""A property or cohort to break down on. You can select the type of the property with breakdown_type.
- `event` (default): a property key
- `person`: a person property key
- `cohort`: an array of cohort IDs (ie `[9581,5812]`)""",
    )
    breakdown_type = serializers.ChoiceField(
        choices=get_args(BREAKDOWN_TYPES),
        required=False,
        help_text="Type of property to break down on.",
        default="event",
    )

    def validate(self, data):
        breakdown_type = data.get("breakdown_type", "event")

        if breakdown_type == "cohort":
            if (
                data.get("breakdown")
                and not isinstance(data["breakdown"], list)
                or any(not isinstance(item, int) for item in data["breakdown"])
            ):
                raise serializers.ValidationError("If breakdown_type is cohort, breakdown must be a list of numbers")

        if (
            (breakdown_type == "event" or data["breakdown_type"] == "person")
            and data.get("breakdown")
            and not isinstance(data["breakdown"], str)
        ):
            raise serializers.ValidationError("If breakdown_type is event or person, breakdown must be a property key")
        return super().validate(data)


class CompareMixin(serializers.Serializer):
    compare = serializers.BooleanField(required=False, help_text="To compare or not")
    compare_to = serializers.CharField(
        required=False,
        help_text="What to compare to",
    )


class ResultsMixin(serializers.Serializer):
    is_cached = serializers.BooleanField(
        help_text="Whether the result is cached. To force a refresh, pass ?refresh=true"
    )
    last_refresh = serializers.DateTimeField(help_text="If the result is cached, when it was last refreshed.")
    timezone = serializers.ChoiceField(choices=TIMEZONES, default="UTC", help_text="Timezone the chart is displayed in")


class TrendResultSerializer(serializers.Serializer):
    data = serializers.ListField(child=serializers.IntegerField(), help_text="The requested counts.")  # type: ignore
    days = serializers.ListField(
        child=serializers.DateField(),
        help_text="The dates corresponding to the data field above.",
    )
    labels = serializers.ListField(
        child=serializers.CharField(),
        help_text="The dates corresponding to the data field above.",
    )
    filter = GenericInsightsSerializer(help_text="The insight that's being returned.")
    label = serializers.CharField(
        help_text="A label describing this result. Will include\n- The event or action\n- Breakdown value\n- If `compare:true`, whether it's `current` or `previous`"
    )  # type: ignore


class TrendResultsSerializer(ResultsMixin):
    result = TrendResultSerializer(many=True)


class TrendSerializer(GenericInsightsSerializer, BreakdownMixin, CompareMixin):
    display = serializers.ChoiceField(
        choices=get_args(DISPLAY_TYPES),
        required=False,
        default="ActionsLineGraph",
        help_text="How to display the data. Will change how the data is returned.",
    )

    formula = serializers.CharField(
        required=False,
        help_text="Combine the result of events or actions into a single number. For example `A + B` or `(A-B)/B`. The letters correspond to the order of the `events` or `actions` lists.",
        allow_blank=True,
    )


class FunnelExclusionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Name of the event to filter on. For example `$pageview` or `user sign up`.")
    properties = PropertySerializer(required=False, help_text=property_help_text)
    funnel_from_step = serializers.IntegerField(default=0, required=False)
    funnel_to_step = serializers.IntegerField(default=1, required=False)


class FunnelStepsResultSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of people in this step.")
    action_id = serializers.CharField(
        help_text="Corresponds to the `id` of the entities passed through to `events` or `actions`."
    )
    average_conversion_time = serializers.FloatField(
        help_text="Average conversion time of person or groups between steps. `null` for the first step."
    )
    median_conversion_time = serializers.FloatField(
        help_text="Median conversion time of person or groups between steps. `null` for the first step."
    )
    converted_people_url = serializers.CharField(
        help_text="Path of a URL to get a list of people that converted after this step. In this format: `/api/person/funnel?...`"
    )
    dropped_people_url = serializers.CharField(
        help_text="Path of a URL to get a list of people that dropped after this step. In this format: `/api/person/funnel?...`"
    )
    order = serializers.CharField(
        help_text="Order of this step in the funnel. The API should return the steps in order anyway."
    )
    # Fields not added to this serializer for simplicity: custom_name, name, order, people, type


class FunnelStepsResultsSerializer(ResultsMixin):
    result = FunnelStepsResultSerializer(many=True)


class FunnelSerializer(GenericInsightsSerializer, BreakdownMixin):
    funnel_window_interval = serializers.IntegerField(
        help_text="Funnel window size. Set in combination with funnel_window_interval, so defaults to 'days'.",
        required=False,
        default=14,
    )
    funnel_window_interval_type = serializers.ChoiceField(
        choices=get_args(FUNNEL_WINDOW_INTERVAL_TYPES),
        required=False,
        help_text="The type of interval. Used in combination with `funnel_window_intervals`.",
        default="days",
    )
    funnel_viz_type = serializers.ChoiceField(
        choices=[el.value for el in FunnelVizType],
        required=False,
        help_text="The visualisation type.\n- `steps` Track instances progress between steps of the funnel\n- `trends` Track how this funnel's conversion rate is trending over time.\n- `time_to_convert` Track how long it takes for instances to convert",
        default="steps",
    )
    funnel_order_type = serializers.ChoiceField(
        choices=[el.value for el in FunnelOrderType],
        required=False,
        help_text="- `ordered` - Step B must happen after Step A, but any number events can happen between A and B.\n- `strict` - Step B must happen directly after Step A without any events in between.\n- `unordered` - Steps can be completed in any sequence.",
        default="ordered",
    )
    exclusions = FunnelExclusionSerializer(
        many=True,
        required=False,
        help_text="Exclude users/groups that completed the specified event between two specific steps. Note that these users/groups will be completely excluded from the entire funnel.",
    )
    aggregation_group_type_index = serializers.IntegerField(
        help_text="Aggregate by users or by groups. `0` means user, `>0` means a group. See interface for the corresponding ID of the group.",
        default=0,
        required=False,
    )
    breakdown_limit = serializers.IntegerField(help_text="", required=False, default=10)
    funnel_window_days = serializers.IntegerField(
        help_text="(DEPRECATED) Funnel window size in days. Use `funnel_window_interval` and `funnel_window_interval_type`",
        required=False,
        default=14,
    )
