from typing import Any, Optional

from django.db.models import Q

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ServerTimingsGathered, action
from posthog.models import ActivityLog, Cohort, FeatureFlag, HogFunction, Insight, NotificationViewed, User
from posthog.models.comment import Comment
from posthog.models.notebook.notebook import Notebook


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

        user_bookmark: Optional[NotificationViewed] = NotificationViewed.objects.filter(
            user=self.context["user"]
        ).first()

        if user_bookmark is None:
            return True
        else:
            # API call from browser only includes milliseconds but python datetime in created_at includes microseconds
            bookmark_date = user_bookmark.last_viewed_activity_date
            return bookmark_date < obj.created_at.replace(microsecond=obj.created_at.microsecond // 1000 * 1000)


class MyNotificationsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    queryset = ActivityLog.objects.all()
    serializer_class = MyNotificationsSerializer
    filter_rewrite_rules = {"project_id": "team_id"}

    @extend_schema(exclude=True)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = self.request.user
        if not isinstance(user, User):
            # this is for mypy
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        params = self.request.GET.dict()
        unread = params.get("unread", None) == "true"

        timer = ServerTimingsGathered()

        with timer("gather_query_parts"):
            # first things this user created
            my_insights = list(
                Insight.objects.filter(created_by=user, team__project_id=self.team.project_id).values_list(
                    "id", flat=True
                )
            )
            my_feature_flags = list(
                FeatureFlag.objects.filter(created_by=user, team__project_id=self.team.project_id).values_list(
                    "id", flat=True
                )
            )
            my_notebooks = list(
                Notebook.objects.filter(created_by=user, team__project_id=self.team.project_id).values_list(
                    "short_id", flat=True
                )
            )
            my_comments = list(
                Comment.objects.filter(created_by=user, team__project_id=self.team.project_id).values_list(
                    "id", flat=True
                )
            )
            my_cohorts = list(
                Cohort.objects.filter(created_by=user, team__project_id=self.team.project_id).values_list(
                    "id", flat=True
                )
            )
            my_hog_functions = list(
                HogFunction.objects.filter(created_by=user, team_id=self.team.pk).values_list("id", flat=True)
            )

            # then things they edited
            interesting_changes = [
                "updated",
                "exported",
                "sharing enabled",
                "sharing disabled",
                "deleted",
                "commented",
            ]
            my_changed_insights = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="Insight",
                )
                .exclude(item_id__in=my_insights)
                .values_list("item_id", flat=True)
            )

            my_changed_notebooks = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="Notebook",
                )
                .exclude(item_id__in=my_notebooks)
                .values_list("item_id", flat=True)
            )

            my_changed_feature_flags = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="FeatureFlag",
                )
                .exclude(item_id__in=my_feature_flags)
                .values_list("item_id", flat=True)
            )

            my_changed_comments = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="Comment",
                )
                .exclude(item_id__in=my_comments)
                .values_list("item_id", flat=True)
            )

            my_changed_cohorts = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="Cohort",
                )
                .exclude(item_id__in=my_cohorts)
                .values_list("item_id", flat=True)
            )

            my_changed_hog_functions = list(
                ActivityLog.objects.filter(
                    team_id=self.team.id,
                    activity__in=interesting_changes,
                    user_id=user.pk,
                    scope="HogFunction",
                )
                .exclude(item_id__in=my_hog_functions)
                .values_list("item_id", flat=True)
            )

            last_read_date = (
                NotificationViewed.objects.filter(user=user).values_list("last_viewed_activity_date", flat=True).first()
            )
            last_read_filter = ""

            if last_read_date and unread:
                # truncate created_at to millisecond precision to match last_read precision
                last_read_filter = f"AND date_trunc('millisecond', created_at) > '{last_read_date.isoformat()}'"

        with timer("query_for_candidate_ids"):
            # before we filter to include only the important changes,
            # we need to deduplicate too frequent changes
            # we only really need to do this on notebooks
            deduplicated_notebook_activity_ids_query = ActivityLog.objects.raw(
                f"""
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
                            WHERE team_id = {self.team_id}
                            -- we only really care about de-duplicating Notebook changes,
                            -- as multiple actual activities are logged for one logical activity
                            AND scope = 'Notebook'
                            AND NOT (user_id = {user.pk} AND user_id IS NOT NULL)
                            {last_read_filter}
                            ORDER BY created_at DESC) AS inner_q) AS counted_q
                WHERE row_number = 1
                """
            )
            deduplicated_notebook_activity_ids = [c.id for c in deduplicated_notebook_activity_ids_query]

        with timer("construct_query"):
            other_peoples_changes = (
                self.queryset.exclude(user=user)
                .filter(team_id=self.team.id)
                .filter(
                    Q(
                        Q(Q(scope="FeatureFlag") & Q(item_id__in=my_feature_flags))
                        | Q(Q(scope="Insight") & Q(item_id__in=my_insights))
                        | Q(
                            Q(scope="Notebook")
                            & Q(item_id__in=my_notebooks)
                            & Q(id__in=deduplicated_notebook_activity_ids)
                        )
                        | Q(Q(scope="Comment") & Q(item_id__in=my_comments))
                        | Q(Q(scope="Cohort") & Q(item_id__in=my_cohorts))
                        | Q(Q(scope="HogFunction") & Q(item_id__in=my_hog_functions))
                    )
                    | Q(
                        # don't want to see creation of these things since that was before the user edited these things
                        Q(activity__in=interesting_changes)
                        & Q(
                            Q(Q(scope="FeatureFlag") & Q(item_id__in=my_changed_feature_flags))
                            | Q(Q(scope="Insight") & Q(item_id__in=my_changed_insights))
                            | Q(
                                Q(scope="Notebook")
                                & Q(item_id__in=my_changed_notebooks)
                                & Q(id__in=deduplicated_notebook_activity_ids)
                            )
                            | Q(Q(scope="Comment") & Q(item_id__in=my_changed_comments))
                            | Q(Q(scope="Cohort") & Q(item_id__in=my_changed_cohorts))
                            | Q(Q(scope="HogFunction") & Q(item_id__in=my_changed_hog_functions))
                        )
                    )
                )
                .order_by("-created_at")
            )

            if last_read_date and unread:
                # truncate created_at to millisecond precision to match last_read precision
                other_peoples_changes = other_peoples_changes.extra(
                    where=["date_trunc('millisecond', created_at) > %s"], params=[last_read_date]
                )

        with timer("query_for_data"):
            page_of_data = other_peoples_changes[:10]

        with timer("serialize"):
            serialized_data = MyNotificationsSerializer(instance=page_of_data, many=True, context={"user": user}).data

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
