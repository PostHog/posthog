from rest_framework import authentication, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.client import sync_execute
from posthog.models import Element, Filter
from posthog.models.element.element import chain_to_elements
from posthog.models.element.sql import GET_ELEMENTS, GET_VALUES
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.util import date_from_clause, parse_timestamps


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


class ElementViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    filter_rewrite_rules = {"team_id": "group__team_id"}

    queryset = Element.objects.all()
    serializer_class = ElementSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    include_in_docs = False

    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        filter = Filter(request=request, team=self.team)

        _, date_to, date_params = parse_timestamps(filter, team=self.team)
        date_from = date_from_clause("toStartOfDay", True)

        prop_filters, prop_filter_params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=filter.property_groups
        )
        result = sync_execute(
            GET_ELEMENTS.format(date_from=date_from, date_to=date_to, query=prop_filters),
            {"team_id": self.team.pk, "timezone": self.team.timezone, **prop_filter_params, **date_params},
        )
        return response.Response(
            [
                {
                    "count": elements[1],
                    "hash": None,
                    "elements": [ElementSerializer(element).data for element in chain_to_elements(elements[0])],
                }
                for elements in result
            ]
        )

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        key = request.GET.get("key")
        value = request.GET.get("value")
        select_regex = '[:|"]{}="(.*?)"'.format(key)

        # Make sure key exists, otherwise could lead to sql injection lower down
        if key not in self.serializer_class.Meta.fields:
            return response.Response([])

        if key == "tag_name":
            select_regex = r"^([-_a-zA-Z0-9]*?)[\.|:]"
            filter_regex = select_regex
            if value:
                filter_regex = r"^([-_a-zA-Z0-9]*?{}[-_a-zA-Z0-9]*?)[\.|:]".format(value)
        else:
            if value:
                filter_regex = '[:|"]{}=".*?{}.*?"'.format(key, value)
            else:
                filter_regex = select_regex

        result = sync_execute(
            GET_VALUES.format(), {"team_id": self.team.id, "regex": select_regex, "filter_regex": filter_regex}
        )
        return response.Response([{"name": value[0]} for value in result])


class LegacyElementViewSet(ElementViewSet):
    legacy_team_compatibility = True
