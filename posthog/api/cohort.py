import csv
from typing import Any, Dict, List, Optional

import posthoganalytics
from django.db.models import Count, QuerySet
from django.db.models.expressions import Value
from django.db.models.sql.query import Query
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.action import calculate_people, filter_by_type
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.constants import INSIGHT_STICKINESS
from posthog.models import Cohort
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.queries.stickiness import (
    stickiness_fetch_people,
    stickiness_format_intervals,
    stickiness_process_entity_type,
)
from posthog.tasks.calculate_cohort import calculate_cohort, calculate_cohort_from_csv


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)
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

    def _handle_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_csv.delay(cohort.pk, distinct_ids_and_emails)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, request)
        else:
            calculate_cohort.delay(cohort_id=cohort.pk)

        posthoganalytics.capture(request.user.distinct_id, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _handle_static(self, cohort: Cohort, request: Request):
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            try:
                filter = Filter(request=request)
                team = request.user.team
                if filter.insight == INSIGHT_STICKINESS:
                    stickiness_filter = StickinessFilter(
                        request=request, team=team, get_earliest_timestamp=self.earliest_timestamp_func
                    )
                    people_distinct_ids = self._fetch_stickiness_people(stickiness_filter, team)
                else:
                    people_distinct_ids = self._fetch_trend_people(filter, team)
                self._calculate_static_by_people(people_distinct_ids, cohort)
            except:
                raise ValueError("This cohort has no conditions")

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_csv.delay(cohort.pk, distinct_ids_and_emails)

    def _calculate_static_by_people(self, people: List[str], cohort: Cohort) -> None:
        calculate_cohort_from_csv.delay(cohort.pk, people)

    def _fetch_stickiness_people(self, filter: StickinessFilter, team: Team) -> List[str]:
        events = stickiness_process_entity_type(team, filter)
        events = stickiness_format_intervals(events, filter)
        people = stickiness_fetch_people(events, team, filter)
        return [person.distinct_ids[0] for person in people if len(person.distinct_ids)]

    def _fetch_trend_people(self, filter: Filter, team: Team) -> List[str]:
        events = filter_by_type(team=team, filter=filter)
        people = calculate_people(team=team, events=events, filter=filter)
        return [person.distinct_ids[0] for person in people if len(person.distinct_ids)]

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        cohort.name = validated_data.get("name", cohort.name)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.deleted = validated_data.get("deleted", cohort.deleted)
        cohort.is_calculating = True
        cohort.save()

        if request.FILES.get("csv") and cohort.is_static:
            self._calculate_static_by_csv(request.FILES["csv"], cohort)

        posthoganalytics.capture(
            request.user.distinct_id,
            "cohort updated",
            {**cohort.get_analytics_metadata(), "updated_by_creator": request.user == cohort.created_by},
        )
        if not cohort.is_static:
            calculate_cohort.delay(cohort_id=cohort.pk)
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
