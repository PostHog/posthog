import operator
from datetime import datetime, timedelta
from functools import reduce
from typing import Any, Optional

from django.db.models import Q
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

    class Meta:
        model = ActivityLog
        exclude = ["team_id"]

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

    def _deduplicated_notebook_activity_ids(self, user: User, since: datetime) -> list[str]:
        """Notebooks save while you type, so one logical edit logs several activities."""
        # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via params list)
        rows = ActivityLog.objects.raw(
            """
            SELECT id
            FROM (SELECT
                    Row_number() over (
                        PARTITION BY five_minute_window, activity, item_id, scope ORDER BY created_at DESC
                    ) AS row_number,
                    *
                    FROM (
                        -- copied from https://stackoverflow.com/a/43028800
                        SELECT to_timestamp(floor(Extract(epoch FROM created_at) / extract(epoch FROM interval '5 min')) *
                                            extract(epoch FROM interval '5 min')) AS five_minute_window,
                               activity, item_id, scope, id, created_at
                        FROM posthog_activitylog
                        WHERE team_id = %s
                        AND scope = 'Notebook'
                        AND (user_id != %s OR user_id IS NULL)
                        AND date_trunc('millisecond', created_at) > %s
                        ORDER BY created_at DESC) AS inner_q) AS counted_q
            WHERE row_number = 1
            """,
            [self.team_id, user.pk, since],
        )
        return [row.id for row in rows]

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
            deduplicated_notebook_activity_ids: list[str] = []
            if owned_items["Notebook"] or changed_items["Notebook"]:
                deduplicated_notebook_activity_ids = self._deduplicated_notebook_activity_ids(user, activity_since)

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
                    self.queryset.exclude(user=user)
                    .filter(team_id=self.team.id, created_at__gte=history_cutoff)
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
                    where=["date_trunc('millisecond', created_at) > %s"], params=[last_read_date]
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

        NotificationViewed.objects.update_or_create(user=user, defaults={"last_viewed_activity_date": bookmark_date})
        return Response(status=status.HTTP_204_NO_CONTENT)
