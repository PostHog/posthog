import operator
from datetime import UTC, datetime, timedelta
from functools import reduce
from typing import Any, Optional, cast
from uuid import UUID

from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import Extract, Floor, RowNumber, Trunc
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ServerTimingsGathered, action
from posthog.models import ActivityLog, NotificationViewed, User
from posthog.models.activity_logging.activity_log import apply_activity_visibility_restrictions
from posthog.models.comment import Comment

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.facade import api as notebooks
from products.product_analytics.backend.facade.models import Insight

# The bell shows the ten newest changes. Without a lower bound the ordered walk reads down the
# whole team history, which grows forever, so only look this far back.
NOTIFICATION_HISTORY_WINDOW = timedelta(days=30)

NOTIFIED_SCOPES = ["FeatureFlag", "Insight", "Notebook", "Comment", "Cohort", "HogFunction"]

INTERESTING_CHANGES = [
    "updated",
    "exported",
    "sharing enabled",
    "sharing disabled",
    "deleted",
    "commented",
]


class MyNotificationsSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()
    unread = serializers.SerializerMethodField()
    detail = serializers.JSONField(
        source="safe_detail", read_only=True, help_text="What changed, with the values of masked fields hidden."
    )

    class Meta:
        model = ActivityLog
        # An explicit list, so that a new internal column such as `credential_id` stays out of the
        # teammate feed.
        fields = [
            "id",
            "user",
            "unread",
            "organization_id",
            "was_impersonated",
            "is_system",
            "client",
            "ip_address",
            "activity",
            "item_id",
            "scope",
            "detail",
            "created_at",
        ]

    def get_unread(self, obj: ActivityLog) -> bool:
        """is the date of this log item newer than the user's bookmark"""
        if "user" not in self.context:
            return False

        bookmark_date: Optional[datetime] = self.context.get("last_read_date")

        if bookmark_date is None:
            return True
        else:
            # API call from browser only includes milliseconds but python datetime in created_at includes microseconds
            return bookmark_date < obj.created_at.replace(microsecond=obj.created_at.microsecond // 1000 * 1000)


class MyNotificationsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = ActivityLog.objects.all()
    serializer_class = MyNotificationsSerializer
    filter_rewrite_rules = {"project_id": "team_id"}

    def _items_the_user_owns(self, user: User) -> dict[str, set[str]]:
        project_id = self.team.project_id
        return {
            "Insight": self._as_item_ids(
                Insight.objects.filter(created_by=user, team__project_id=project_id).values_list("id", flat=True)
            ),
            "FeatureFlag": self._as_item_ids(
                FeatureFlag.objects_including_soft_deleted.filter(
                    created_by=user, team__project_id=project_id
                ).values_list("id", flat=True)
            ),
            "Notebook": self._as_item_ids(notebooks.get_notebook_short_ids_for_creator(project_id, user.id)),
            "Comment": self._as_item_ids(
                Comment.objects.filter(created_by=user, team__project_id=project_id).values_list("id", flat=True)
            ),
            "Cohort": self._as_item_ids(
                Cohort.objects.filter(created_by=user, team__project_id=project_id).values_list("id", flat=True)
            ),
            "HogFunction": self._as_item_ids(
                HogFunction.objects.filter(created_by=user, team_id=self.team.pk).values_list("id", flat=True)
            ),
        }

    def _items_the_user_changed(self, user: User, owned: dict[str, set[str]], since: datetime) -> dict[str, set[str]]:
        changed: dict[str, set[str]] = {scope: set() for scope in NOTIFIED_SCOPES}
        rows = ActivityLog.objects.filter(
            team_id=self.team.id,
            activity__in=INTERESTING_CHANGES,
            user_id=user.pk,
            scope__in=NOTIFIED_SCOPES,
            created_at__gte=since,
        ).values_list("scope", "item_id")
        for scope, item_id in rows:
            if item_id is not None and item_id not in owned[scope]:
                changed[scope].add(item_id)
        return changed

    @staticmethod
    def _as_item_ids(values: Any) -> set[str]:
        return {str(value) for value in values}

    @staticmethod
    def _scope_filter(items_per_scope: dict[str, set[str]]) -> Optional[Q]:
        """One OR branch per scope that actually has items, so empty scopes cost nothing."""
        branches = [Q(scope=scope, item_id__in=item_ids) for scope, item_ids in items_per_scope.items() if item_ids]
        return reduce(operator.or_, branches) if branches else None

    @staticmethod
    def _deduplicated_notebook_activity_ids(
        visible_changes: QuerySet[ActivityLog], notebook_ids: set[str], since: datetime
    ) -> list[UUID]:
        """Notebooks save while you type, so show the newest visible change in each five-minute window."""
        return list(
            visible_changes.filter(scope="Notebook", item_id__in=notebook_ids)
            .alias(millisecond=Trunc("created_at", "milliseconds", tzinfo=UTC))
            .filter(millisecond__gt=since)
            .alias(
                position=Window(
                    expression=RowNumber(),
                    partition_by=[Floor(Extract("created_at", "epoch", tzinfo=UTC) / 300), F("activity"), F("item_id")],
                    order_by=[F("created_at").desc(), F("id").desc()],
                )
            )
            .filter(position=1)
            .values_list("pk", flat=True)
        )

    @extend_schema(exclude=True)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = self.request.user
        if not isinstance(user, User):
            # this is for mypy
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        params = self.request.GET.dict()
        unread = params.get("unread", None) == "true"

        timer = ServerTimingsGathered()
        history_cutoff = timezone.now() - NOTIFICATION_HISTORY_WINDOW

        with timer("gather_query_parts"):
            owned_items = self._items_the_user_owns(user)
            changed_items = self._items_the_user_changed(user, owned_items, history_cutoff)

            last_read_date = (
                NotificationViewed.objects.filter(user=user).values_list("last_viewed_activity_date", flat=True).first()
            )
            activity_since = max(last_read_date, history_cutoff) if (last_read_date and unread) else history_cutoff

        with timer("query_for_candidate_ids"):
            # before we filter to include only the important changes,
            # we need to deduplicate too frequent changes
            # we only really need to do this on notebooks
            visible_changes = apply_activity_visibility_restrictions(
                self.queryset.filter(team_id=self.team.id, created_at__gte=history_cutoff).exclude(user=user), user
            )
            notebook_ids = owned_items["Notebook"] | changed_items["Notebook"]
            deduplicated_notebook_activity_ids = (
                self._deduplicated_notebook_activity_ids(visible_changes, notebook_ids, activity_since)
                if notebook_ids
                else []
            )

        with timer("construct_query"):
            owned_filter = self._scope_filter(owned_items)
            changed_filter = self._scope_filter(changed_items)
            if changed_filter is not None:
                # don't want to see creation of these things since that was before the user edited these things
                changed_filter = Q(activity__in=INTERESTING_CHANGES) & changed_filter

            filters = [f for f in (owned_filter, changed_filter) if f is not None]
            interesting = reduce(operator.or_, filters) if filters else None

            other_peoples_changes = (
                self.queryset.none()
                if interesting is None
                else (
                    visible_changes.select_related("user")
                    .filter(interesting)
                    # notebooks log several activities per logical edit, so only the deduplicated ones count
                    .filter(~Q(scope="Notebook") | Q(id__in=deduplicated_notebook_activity_ids))
                    .order_by("-created_at")
                )
            )

            if last_read_date and unread:
                # truncate created_at to millisecond precision to match last_read precision
                # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
                other_peoples_changes = other_peoples_changes.extra(
                    where=["date_trunc('millisecond', posthog_activitylog.created_at) > %s"], params=[last_read_date]
                )

        with timer("query_for_data"):
            page_of_data = other_peoples_changes[:10]

        with timer("serialize"):
            serialized_data = MyNotificationsSerializer(
                instance=page_of_data, many=True, context={"user": user, "last_read_date": last_read_date}
            ).data

        response = Response(
            status=status.HTTP_200_OK,
            data={
                "results": serialized_data,
                "last_read": last_read_date if last_read_date else None,
            },
        )

        response.headers["Server-Timing"] = timer.to_header_string()

        return response

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False)
    def bookmark(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user
        bookmark_date = request.data.pop("bookmark", None)

        if bookmark_date is None:
            raise ValidationError("must provide a bookmark date")

        NotificationViewed.objects.update_or_create(
            user=cast(User, user), defaults={"last_viewed_activity_date": bookmark_date}
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
