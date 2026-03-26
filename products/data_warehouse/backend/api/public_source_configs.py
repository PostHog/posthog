from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.temporal.data_imports.sources import SourceRegistry


class SuggestedTableSerializer(serializers.Serializer):
    table = serializers.CharField(help_text="Table name to suggest.")
    tooltip = serializers.CharField(
        allow_null=True, required=False, help_text="Tooltip explaining why this table is suggested."
    )


class PublicSourceConfigSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Source type identifier (e.g. 'Stripe', 'Postgres').")
    label = serializers.CharField(allow_null=True, help_text="Display label for the source.")
    iconPath = serializers.CharField(help_text="Path to the source's icon asset.")
    iconClassName = serializers.CharField(allow_null=True, required=False, help_text="Optional CSS class for the icon.")
    caption = serializers.CharField(allow_null=True, required=False, help_text="Short description of the source.")
    permissionsCaption = serializers.CharField(
        allow_null=True, required=False, help_text="Description of required permissions."
    )
    docsUrl = serializers.CharField(allow_null=True, required=False, help_text="Link to the source's documentation.")
    betaSource = serializers.BooleanField(allow_null=True, required=False, help_text="Whether this source is in beta.")
    unreleasedSource = serializers.BooleanField(
        allow_null=True, required=False, help_text="Whether this source is unreleased."
    )
    featured = serializers.BooleanField(
        allow_null=True, required=False, help_text="Whether this source should be prominently displayed."
    )
    existingSource = serializers.BooleanField(
        allow_null=True, required=False, help_text="Whether this source already exists for the team."
    )
    disabledReason = serializers.CharField(
        allow_null=True, required=False, help_text="Reason why the source is disabled, if applicable."
    )
    featureFlag = serializers.CharField(allow_null=True, required=False, help_text="Feature flag gating this source.")
    fields = serializers.JSONField(
        help_text="Input field schemas needed to render the setup form. Each entry is a polymorphic field config (input, select, oauth, file-upload, switch-group, or ssh-tunnel)."
    )
    webhookFields = serializers.JSONField(
        allow_null=True,
        required=False,
        help_text="Input field schemas for webhook-based setup, if the source supports webhooks.",
    )
    webhookSetupCaption = serializers.CharField(
        allow_null=True, required=False, help_text="Caption shown during webhook setup."
    )
    suggestedTables = SuggestedTableSerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text="Tables to suggest enabling, with optional tooltip.",
    )


@extend_schema(tags=["data_warehouse"])
class PublicSourceConfigViewSet(viewsets.ViewSet):
    """
    Public (unauthenticated) endpoint that returns the full SourceConfig
    for every registered data warehouse import source — including the
    input field schemas needed to render setup forms.

    This is the data-warehouse equivalent of ``/api/public_hog_function_templates``.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = PublicSourceConfigSerializer

    def list(self, request: Request) -> Response:
        sources = SourceRegistry.get_all_sources()

        results = {str(source_type): source.get_source_config.model_dump() for source_type, source in sources.items()}

        return Response(status=status.HTTP_200_OK, data=results)
