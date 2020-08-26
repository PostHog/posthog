import json

from django.db.models import Count, Prefetch, QuerySet
from rest_framework import authentication, request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.models import Element, ElementGroup, Event, Filter, Team
from posthog.utils import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication


class ElementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Element
        fields = [
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


class ElementViewSet(viewsets.ModelViewSet):
    queryset = Element.objects.all()
    serializer_class = ElementSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        return queryset.filter(group__team=self.request.user.team_set.get())

    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request) -> response.Response:
        team = self.request.user.team_set.get()
        filter = Filter(request=request)

        events = (
            Event.objects.filter(team=team, event="$autocapture")
            .filter(filter.properties_to_Q(team_id=team.pk))
            .filter(filter.date_filter_Q)
        )

        events = events.values("elements_hash").annotate(count=Count(1)).order_by("-count")[0:100]

        groups = ElementGroup.objects.filter(
            team=team, hash__in=[item["elements_hash"] for item in events]
        ).prefetch_related(Prefetch("element_set", queryset=Element.objects.order_by("order", "id")))

        return response.Response(
            [
                {
                    "count": item["count"],
                    "hash": item["elements_hash"],
                    "elements": [
                        ElementSerializer(element).data
                        for element in [group for group in groups if group.hash == item["elements_hash"]][
                            0
                        ].element_set.all()
                    ],
                }
                for item in events
            ]
        )

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request) -> response.Response:
        key = request.GET.get("key")
        params = []
        where = ""

        # Make sure key exists, otherwise could lead to sql injection lower down
        if key not in self.serializer_class.Meta.fields:
            return response.Response([])

        if request.GET.get("value"):
            where = ' AND "posthog_element"."{}" LIKE %s'.format(key)
            params.append("%{}%".format(request.GET["value"]))

        # This samples a bunch of elements with that property, and then orders them by most popular in that sample
        # This is much quicker than trying to do this over the entire table
        values = Element.objects.raw(
            """
            SELECT
                value, COUNT(1) as id
            FROM ( 
                SELECT
                    ("posthog_element"."{key}") as "value"
                FROM
                    "posthog_element"
                INNER JOIN
                    "posthog_elementgroup" ON ("posthog_elementgroup".id="posthog_element"."group_id")
                WHERE
                    ("posthog_element"."{key}") IS NOT NULL {where} AND
                    ("posthog_elementgroup"."team_id" = {team_id})
                LIMIT 10000
            ) as "value"
            GROUP BY value
            ORDER BY id DESC
            LIMIT 50;
        """.format(
                where=where, team_id=request.user.team_set.get().pk, key=key
            ),
            params,
        )

        return response.Response([{"name": value.value} for value in values])
