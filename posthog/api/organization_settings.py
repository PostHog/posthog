from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from posthog.models.organization_settings import OrganizationSetting
from posthog.services.organization_settings import OrganizationSettingsService
from posthog.permissions.organization_settings import OrganizationSettingsViewPermission
from posthog.permissions.mixins import OrganizationSettingsMixin


class OrganizationSettingSerializer(serializers.ModelSerializer):
    """Serializer for organization settings"""

    class Meta:
        model = OrganizationSetting
        fields = ["id", "setting_key", "setting_value", "created_at", "updated_at", "created_by", "updated_by"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "updated_by"]

    def validate_setting_value(self, value):
        """Validate setting value against its definition"""
        setting_key = self.initial_data.get("setting_key")
        if not setting_key:
            raise ValidationError("setting_key is required")

        try:
            from posthog.models.organization_setting_definitions import get_setting_definition

            definition = get_setting_definition(setting_key)
            if not definition:
                raise ValidationError(f"No definition found for setting key: {setting_key}")

            # Create a temporary setting object for validation
            temp_setting = OrganizationSetting(setting_key=setting_key, setting_value=value)
            temp_setting._validate_setting_value(definition)
            return value
        except ValidationError as e:
            raise ValidationError(f"Validation failed for {setting_key}: {str(e)}")

    def create(self, validated_data):
        """Create setting with user tracking"""
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Update setting with user tracking"""
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)


class OrganizationSettingsBulkSerializer(serializers.Serializer):
    """Serializer for bulk setting operations"""

    settings = serializers.ListField(
        child=serializers.DictField(),
        help_text="Array of settings to update: [{'setting_key': 'key', 'setting_value': value}, ...]",
    )

    def validate_settings(self, settings):
        """Validate all settings in bulk operation"""
        validated_settings = []

        for setting_data in settings:
            setting_key = setting_data.get("setting_key")
            setting_value = setting_data.get("setting_value")

            if not setting_key:
                raise ValidationError("Each setting must have a setting_key")

            try:
                from posthog.models.organization_setting_definitions import get_setting_definition

                definition = get_setting_definition(setting_key)
                if not definition:
                    raise ValidationError(f"No definition found for setting key: {setting_key}")

                # Create a temporary setting object for validation
                temp_setting = OrganizationSetting(setting_key=setting_key, setting_value=setting_value)
                temp_setting._validate_setting_value(definition)
                validated_settings.append(setting_data)
            except ValidationError as e:
                raise ValidationError(f"Validation failed for {setting_key}: {str(e)}")

        return validated_settings


class OrganizationSettingsViewSet(OrganizationSettingsMixin, viewsets.ModelViewSet):
    """ViewSet for organization settings"""

    serializer_class = OrganizationSettingSerializer
    permission_classes = [OrganizationSettingsViewPermission]  # Use view permission by default
    http_method_names = ["get", "put", "post"]  # Only allow GET, PUT, POST

    def get_queryset(self):
        """Get settings for the current organization"""
        organization = self.request.user.organization
        return OrganizationSetting.objects.filter(organization=organization)

    def perform_create(self, serializer):
        """Create setting with organization context"""
        serializer.save(organization=self.request.user.organization)

    def update(self, request, *args, **kwargs):
        """Override update to perform upsert operation"""
        setting_key = request.data.get("setting_key")
        setting_value = request.data.get("setting_value")

        if not setting_key:
            return Response({"error": "setting_key is required"}, status=status.HTTP_400_BAD_REQUEST)

        organization = request.user.organization
        user = request.user

        # Check if user can edit this setting
        if not self.check_setting_permission(setting_key, user, organization):
            return Response({"error": f"User cannot edit setting: {setting_key}"}, status=status.HTTP_403_FORBIDDEN)

        # Perform upsert operation
        try:
            service = OrganizationSettingsService(organization)
            setting = service.set_setting(setting_key, setting_value, user)
            serializer = self.get_serializer(setting)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Bulk update multiple settings"""
        serializer = OrganizationSettingsBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        organization = request.user.organization
        user = request.user

        updated_settings = []
        for setting_data in serializer.validated_data["settings"]:
            setting_key = setting_data["setting_key"]
            setting_value = setting_data["setting_value"]

            # Check if user can edit this setting
            if not self.check_setting_permission(setting_key, user, organization):
                return Response({"error": f"User cannot edit setting: {setting_key}"}, status=status.HTTP_403_FORBIDDEN)

            # Update the setting
            service = OrganizationSettingsService(organization)
            setting = service.set_setting(setting_key, setting_value, user)
            updated_settings.append(setting)

        result_serializer = OrganizationSettingSerializer(updated_settings, many=True)
        return Response(result_serializer.data)
