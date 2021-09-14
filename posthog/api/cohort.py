import csv
from typing import Any, Dict, List, Optional, cast

import posthoganalytics
from django.db.models import Count, QuerySet
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from sentry_sdk.api import capture_exception

from posthog.api.action import calculate_people, filter_by_type
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.constants import TRENDS_STICKINESS
from posthog.models import Cohort, Entity
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.queries.stickiness import (
    stickiness_fetch_people,
    stickiness_format_intervals,
    stickiness_process_entity_type,
)
from posthog.tasks.calculate_cohort import calculate_cohort, calculate_cohort_ch, calculate_cohort_from_list
from posthog.utils import is_clickhouse_enabled


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    count = serializers.SerializerMethodField()
    earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "groups",
            "deleted",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "is_static",
        ]
        read_only_fields = [
            "id",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
        ]

    def _handle_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, request)
        else:
            if is_clickhouse_enabled():
                calculate_cohort_ch.delay(cohort.id)
            else:
                calculate_cohort.delay(cohort.id)

        posthoganalytics.capture(request.user.distinct_id, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _handle_static(self, cohort: Cohort, request: Request):
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            try:
                filter = Filter(request=request)
                team = cast(User, request.user).team
                target_entity = get_target_entity(request)
                if filter.shown_as == TRENDS_STICKINESS:
                    stickiness_filter = StickinessFilter(
                        request=request, team=team, get_earliest_timestamp=self.earliest_timestamp_func
                    )
                    self._handle_stickiness_people(target_entity, cohort, stickiness_filter)
                else:
                    self._handle_trend_people(target_entity, cohort, filter, request)
            except Exception as e:
                capture_exception(e)
                raise ValueError("This cohort has no conditions")

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def _calculate_static_by_people(self, people: List[str], cohort: Cohort) -> None:
        calculate_cohort_from_list.delay(cohort.pk, people)

    def _handle_stickiness_people(self, target_entity: Entity, cohort: Cohort, filter: StickinessFilter) -> None:
        events = stickiness_process_entity_type(target_entity, cohort.team, filter)
        events = stickiness_format_intervals(events, filter)
        people = stickiness_fetch_people(events, cohort.team, filter)
        ids = [person.distinct_ids[0] for person in people if len(person.distinct_ids)]
        self._calculate_static_by_people(ids, cohort)

    def _handle_trend_people(self, target_entity: Entity, cohort: Cohort, filter: Filter, request: Request) -> None:
        events = filter_by_type(entity=target_entity, team=cohort.team, filter=filter)
        people = calculate_people(team=cohort.team, events=events, filter=filter, request=request)
        ids = [person.distinct_ids[0] for person in people if len(person.distinct_ids)]
        self._calculate_static_by_people(ids, cohort)

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        cohort.name = validated_data.get("name", cohort.name)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        deleted_state = validated_data.get("deleted", None)

        is_deletion_change = deleted_state is not None
        if is_deletion_change:
            cohort.deleted = deleted_state

        if not cohort.is_static and not is_deletion_change:
            cohort.is_calculating = True
        cohort.save()

        if not deleted_state:
            if cohort.is_static:
                # You can't update a static cohort using the trend/stickiness thing
                if request.FILES.get("csv"):
                    self._calculate_static_by_csv(request.FILES["csv"], cohort)
            else:
                if is_clickhouse_enabled():
                    calculate_cohort_ch.delay(cohort.id)
                else:
                    calculate_cohort.delay(cohort.id)

        posthoganalytics.capture(
            request.user.distinct_id,
            "cohort updated",
            {**cohort.get_analytics_metadata(), "updated_by_creator": request.user == cohort.created_by},
        )

        return cohort

    def get_count(self, action: Cohort) -> Optional[int]:
        if hasattr(action, "count"):
            return action.count  # type: ignore
        return None


class CohortViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count("people"))
        return queryset.select_related("created_by").order_by("id")
