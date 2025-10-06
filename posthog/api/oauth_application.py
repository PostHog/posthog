from rest_framework import mixins, serializers, viewsets

from posthog.models.oauth import OAuthApplication


class OAuthApplicationPublicMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = OAuthApplication
        fields = ["name", "client_id"]
        read_only_fields = ["name", "client_id"]


class OAuthApplicationPublicMetadataViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Exposes the public metadata (name, client_id) of an OAuth application,
    identified by its client_id.
    Accessible without authentication.
    """

    queryset = OAuthApplication.objects.all()
    serializer_class = OAuthApplicationPublicMetadataSerializer
    permission_classes = []
    authentication_classes = []
    lookup_field = "client_id"
    lookup_url_kwarg = "client_id"
