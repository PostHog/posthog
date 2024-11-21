from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import DataColorTheme


class DataColorThemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataColorTheme
        fields = [
            "name",
            "theme",
        ]


class DataColorThemeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DataColorTheme.objects.all()
    serializer_class = DataColorThemeSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
