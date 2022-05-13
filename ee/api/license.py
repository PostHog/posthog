import requests
from django.conf import settings
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import mixins, request, serializers, viewsets
from rest_framework.response import Response

from ee.models.license import License, LicenseError
from posthog.models.organization import Organization
from posthog.models.team import Team


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = [
            "id",
            "key",
            "plan",
            "valid_until",
            "max_users",
            "created_at",
        ]
        read_only_fields = ["plan", "valid_until", "max_users"]

    def validate(self, data):
        validation = requests.post("https://license.posthog.com/licenses/activate", data={"key": data["key"]})
        resp = validation.json()
        if not validation.ok:
            raise LicenseError(resp["code"], resp["detail"])
        data["valid_until"] = resp["valid_until"]
        data["plan"] = resp["plan"]
        data["max_users"] = resp.get("max_users", 0)
        return data


class LicenseViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if getattr(settings, "MULTI_TENANCY", False):
            return License.objects.none()

        return super().get_queryset()

    def destroy(self, request: request.Request, pk=None, **kwargs) -> Response:
        license = get_object_or_404(License, pk=pk)
        validation = requests.post("https://license.posthog.com/licenses/deactivate", data={"key": license.key})
        validation.raise_for_status()

        has_another_valid_license = License.objects.filter(valid_until__gte=now()).exclude(pk=pk).exists()
        if not has_another_valid_license:
            teams = Team.objects.exclude(is_demo=True).order_by("pk")[1:]
            for team in teams:
                team.delete()

            #  delete any organization where we've deleted all teams
            # there is no way in the interface to create multiple organizations so we won't bother informing people that this is happening
            for organization in Organization.objects.all():
                if organization.teams.count() == 0:
                    organization.delete()

        license.delete()

        return Response({"ok": True})
