from typing import Any

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.organization_integration import OrganizationIntegration


class OrganizationIntegrationSerializer(serializers.ModelSerializer):
    """Serializer for organization-level integrations."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = OrganizationIntegration
        fields = [
            "id",
            "kind",
            "integration_id",
            "config",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = fields


class EnvironmentMappingUpdateSerializer(serializers.Serializer):
    production = serializers.IntegerField(required=True)
    preview = serializers.IntegerField(required=False)
    development = serializers.IntegerField(required=False)


class OrganizationIntegrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for organization-level integrations.

    Provides read-only access to integrations that are scoped to the entire organization
    (vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

    This is read-only. Creation is handled by the integration installation flows
    (e.g., Vercel marketplace installation). Deletion requires contacting support
    due to billing implications.
    """

    scope_object = "organization_integration"
    queryset = OrganizationIntegration.objects.select_related("created_by").all()
    serializer_class = OrganizationIntegrationSerializer

    @action(detail=True, methods=["patch"], url_path="environment-mapping")
    def environment_mapping(self, request: Request, **kwargs) -> Response:
        integration = self.get_object()

        if integration.config.get("type") != "connectable":
            return Response(
                {"detail": "Environment mapping is only supported for connectable integrations."}, status=400
            )

        serializer = EnvironmentMappingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        production_id = serializer.validated_data["production"]
        preview_id = serializer.validated_data.get("preview", production_id)
        development_id = serializer.validated_data.get("development", production_id)

        from posthog.models.team import Team

        org = integration.organization
        for tid in {production_id, preview_id, development_id}:
            if not Team.objects.filter(pk=tid, organization=org).exists():
                return Response({"detail": f"Project {tid} does not belong to this organization."}, status=400)

        from posthog.models.integration import Integration as TeamIntegration

        from ee.vercel.client import VercelAPIClient
        from ee.vercel.integration import VercelIntegration

        teams_by_id: dict[int, Team] = {}
        for tid in {production_id, preview_id, development_id}:
            teams_by_id[tid] = Team.objects.get(pk=tid, organization=org)
            TeamIntegration.objects.get_or_create(
                team=teams_by_id[tid],
                kind=TeamIntegration.IntegrationKind.VERCEL,
                integration_id=str(tid),
                defaults={"config": {"type": "connectable"}},
            )

        integration.config["environment_mapping"] = {
            "production": production_id,
            "preview": preview_id,
            "development": development_id,
        }
        integration.save(update_fields=["config"])

        production_team = teams_by_id[production_id]
        preview_team = teams_by_id[preview_id]
        dev_team = teams_by_id[development_id]

        production_resource = TeamIntegration.objects.filter(
            team=production_team, kind=TeamIntegration.IntegrationKind.VERCEL
        ).first()

        if not production_resource:
            return Response(
                {"detail": "Failed to find or create production resource. Please reconnect the integration."},
                status=500,
            )

        access_token = integration.sensitive_config.get("credentials", {}).get(
            "access_token"
        ) or integration.config.get("credentials", {}).get("access_token")
        if access_token and integration.integration_id:
            all_same = production_id == preview_id == development_id
            secrets: list[dict[str, Any]] = [
                {
                    "name": "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN",
                    "value": production_team.api_token,
                    **(
                        {}
                        if all_same
                        else {
                            "environmentOverrides": {
                                **({"preview": preview_team.api_token} if preview_id != production_id else {}),
                                **({"development": dev_team.api_token} if development_id != production_id else {}),
                            }
                        }
                    ),
                },
                {
                    "name": "NEXT_PUBLIC_POSTHOG_HOST",
                    "value": VercelIntegration._build_secrets(production_team)[1]["value"],
                },
            ]
            client = VercelAPIClient(bearer_token=access_token)
            client.import_resource(
                integration_config_id=integration.integration_id,
                resource_id=str(production_resource.pk),
                product_id="posthog",
                name=production_team.name,
                secrets=secrets,
            )

        return Response(OrganizationIntegrationSerializer(integration).data)
