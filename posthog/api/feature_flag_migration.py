import logging
from typing import Any

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.feature_flag_providers import provider_registry
from posthog.models.feature_flag.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)


class FeatureFlagMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """API endpoints for feature flag migration from external providers"""

    @action(methods=["POST"], detail=False)
    def fetch_external_flags(self, request: Request) -> Response:
        """Fetch feature flags from external providers"""
        provider_name = request.data.get("provider")
        api_key = request.data.get("api_key")
        project_key = request.data.get("project_key", "")
        environment = request.data.get("environment", "production")

        if not provider_name or not api_key:
            return Response({"error": "Provider and API key are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get provider instance
        provider = provider_registry.get_provider(provider_name, rate_limiter=getattr(self, 'rate_limiter', None))
        if not provider:
            return Response(
                {"error": f"Provider '{provider_name}' is not supported"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Use the provider to fetch flags
            return provider.fetch_flags(api_key, project_key, environment)

        except Exception as e:
            logger.exception(f"Error fetching flags from {provider_name}: {e}")
            return Response(
                {"error": f"Failed to fetch flags: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(methods=["POST"], detail=False)
    def extract_field_mappings(self, request: Request) -> Response:
        """Extract unique fields from selected flags for mapping to PostHog fields"""
        provider_name = request.data.get("provider")
        selected_flags = request.data.get("selected_flags", [])

        if not provider_name or not selected_flags:
            return Response(
                {"error": "Provider and selected flags are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get provider instance
        provider = provider_registry.get_provider(provider_name)
        if not provider:
            return Response(
                {"error": f"Provider '{provider_name}' is not supported"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Extract unique fields from all selected flags
            unique_fields = set()

            for flag in selected_flags:
                # Use provider-specific field extraction
                field_infos = provider.extract_fields_from_flag(flag)
                for field_info in field_infos:
                    unique_fields.add(field_info)

                # Also check transformed conditions as backup
                conditions = flag.get("conditions", [])
                for condition in conditions:
                    properties = condition.get("properties", [])
                    for prop in properties:
                        if prop.get("type") == "cohort":
                            continue

                        field_info = provider.extract_field_info_from_property(prop)
                        if field_info:
                            unique_fields.add(field_info)

            # Create field mapping suggestions
            field_mappings = []
            for field_info in sorted(unique_fields, key=lambda x: x.display_name.lower()):
                # Get default PostHog mapping for known fields
                default_posthog_field = self._get_default_posthog_mapping(field_info.field_type, field_info.key)
                auto_selected = default_posthog_field is not None

                mapping = {
                    "external_key": field_info.key,
                    "external_type": field_info.field_type,
                    "display_name": field_info.display_name,
                    "posthog_field": default_posthog_field,
                    "posthog_type": self._get_posthog_field_type(default_posthog_field),
                    "auto_selected": auto_selected,
                    "options": self._get_posthog_field_options(field_info.field_type),
                }
                field_mappings.append(mapping)

            return Response({
                "field_mappings": field_mappings,
                "total_fields": len(field_mappings)
            })

        except Exception as e:
            logger.exception(f"Error extracting field mappings for {provider_name}: {e}")
            return Response(
                {"error": f"Failed to extract field mappings: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(methods=["POST"], detail=False)
    def import_flags(self, request: Request) -> Response:
        """Import selected feature flags to PostHog"""
        provider_name = request.data.get("provider")
        selected_flags = request.data.get("selected_flags", [])
        field_mappings = request.data.get("field_mappings", {})
        environment = request.data.get("environment", "production")

        if not provider_name or not selected_flags:
            return Response(
                {"error": "Provider and selected flags are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get provider instance
        provider = provider_registry.get_provider(provider_name)
        if not provider:
            return Response(
                {"error": f"Provider '{provider_name}' is not supported"},
                status=status.HTTP_400_BAD_REQUEST
            )

        imported_flags = []
        failed_imports = []

        for flag_data in selected_flags:
            try:
                # Validate flag has proper field mappings
                validation_result, error_message = self._validate_flag_field_mappings(
                    flag_data, field_mappings, provider
                )
                if not validation_result:
                    failed_imports.append({"flag": flag_data, "error": error_message})
                    continue

                # Convert external flag to PostHog format
                posthog_flag_data = self._convert_to_posthog_format(flag_data, field_mappings)

                # Ensure unique flag key by adding suffix if needed
                original_flag_key = posthog_flag_data["key"]
                unique_flag_key = self._generate_unique_flag_key(original_flag_key)
                posthog_flag_data["key"] = unique_flag_key

                # Create the new flag
                new_flag = FeatureFlag.objects.create(
                    team=self.team, created_by=request.user, last_modified_by=request.user, **posthog_flag_data
                )

                import_result = {
                    "external_flag": flag_data,
                    "posthog_flag": {
                        "id": new_flag.id,
                        "key": new_flag.key,
                        "name": new_flag.name,
                        "active": new_flag.active,
                    },
                }

                # Add note if key was renamed due to conflict
                if unique_flag_key != original_flag_key:
                    import_result["key_renamed"] = {
                        "original": original_flag_key,
                        "new": unique_flag_key,
                        "reason": "Key already existed, suffix added to avoid conflict",
                    }

                imported_flags.append(import_result)

            except Exception as e:
                logger.exception(f"Error importing flag {flag_data.get('key', 'unknown')}: {e}")
                failed_imports.append({"flag": flag_data, "error": str(e)})

        return Response(
            {
                "imported_flags": imported_flags,
                "failed_imports": failed_imports,
                "success_count": len(imported_flags),
                "failure_count": len(failed_imports),
            }
        )

    def _validate_flag_field_mappings(self, flag_data, field_mappings, provider):
        """Validate that all required fields in a flag have proper mappings."""
        unmapped_fields = []

        # Check all conditions for unmapped fields
        conditions = flag_data.get("conditions", [])
        for condition in conditions:
            properties = condition.get("properties", [])
            for prop in properties:
                # Skip cohort properties - they're handled separately
                if prop.get("type") == "cohort":
                    continue

                # Get the external key that would be used
                external_key = provider.get_external_key_from_property(prop)
                if external_key:
                    # Check if this field has a mapping
                    field_mapping = field_mappings.get(external_key)
                    if not field_mapping or not field_mapping.get("posthog_field"):
                        unmapped_fields.append(external_key)

        if unmapped_fields:
            return False, f"Flag contains unmapped fields: {', '.join(unmapped_fields)}. All fields used in flag conditions must be mapped to PostHog properties."

        return True, None

    def _convert_to_posthog_format(self, external_flag: dict[str, Any], field_mappings: dict[str, Any]) -> dict[str, Any]:
        """Convert external flag format to PostHog FeatureFlag format"""
        # Apply field mappings if provided
        key = field_mappings.get("key", {}).get("posthog_field") or external_flag.get("key", "")
        name = field_mappings.get("name", {}).get("posthog_field") or external_flag.get("name", external_flag.get("key", ""))

        # Build filters structure for PostHog
        filters = {"groups": []}

        conditions = external_flag.get("conditions", [])
        if conditions:
            for condition in conditions:
                group = {
                    "properties": condition.get("properties", []),
                    "rollout_percentage": condition.get("rollout_percentage", 100),
                }
                if condition.get("variant"):
                    group["variant"] = condition["variant"]
                filters["groups"].append(group)
        else:
            # Default group with 100% rollout if no conditions
            filters["groups"].append(
                {
                    "properties": [],
                    "rollout_percentage": 100,
                }
            )

        # Handle variants
        variants = external_flag.get("variants", [])
        if variants:
            filters["multivariate"] = {"variants": variants}

        return {
            "key": key,
            "name": name,
            "filters": filters,
            "active": external_flag.get("enabled", True),
            "version": 1,
        }

    def _generate_unique_flag_key(self, original_key: str) -> str:
        """Generate a unique flag key by adding a suffix if the key already exists"""
        if not original_key:
            original_key = "imported_flag"

        # Check if the original key is available
        if not FeatureFlag.objects.filter(team=self.team, key=original_key, deleted=False).exists():
            return original_key

        # Generate unique key with suffix
        counter = 1
        while True:
            candidate_key = f"{original_key}_{counter}"
            if not FeatureFlag.objects.filter(team=self.team, key=candidate_key, deleted=False).exists():
                return candidate_key
            counter += 1

            # Safety break to avoid infinite loop (though unlikely with reasonable usage)
            if counter > 1000:
                # Fallback with timestamp if somehow we have 1000+ duplicate keys
                import time
                timestamp = int(time.time())
                return f"{original_key}_{timestamp}"

    def _get_default_posthog_mapping(self, field_type: str, external_key: str) -> str:
        """Get default PostHog field mapping for known field keys/criteria"""
        # Segments should not be auto-mapped - they need manual handling
        if field_type == "segment":
            return None

        # Map external field keys/names to PostHog properties
        mapping = {
            # Identity fields
            "email": "email",
            "user_id": "distinct_id",
            "distinct_id": "distinct_id",
            "key": "distinct_id",  # LaunchDarkly uses "key" for user ID
            # Geographic fields
            "country": "$geoip_country_code",
            "region": "$geoip_subdivision_1_code",
            "city": "$geoip_city_name",
            "ip": "$ip",
            # Device/Browser fields
            "browser_name": "$browser",
            "browser_version": "$browser_version",
            "os_name": "$os",
            "os_version": "$os_version",
            "device": "$device_type",
            "device_model": "$device_type",
        }

        return mapping.get(external_key.lower())

    def _get_posthog_field_type(self, posthog_field: str) -> str:
        """Get the PostHog field type based on the field name"""
        if not posthog_field:
            return "person"

        # System properties start with $
        if posthog_field.startswith("$"):
            return "event"

        # Default to person properties
        return "person"

    def _get_posthog_field_options(self, field_type: str) -> list:
        """Get available PostHog field options for the dropdown"""
        # This could be expanded to return actual available properties from the team
        common_options = [
            {"key": "email", "label": "Email", "type": "person"},
            {"key": "distinct_id", "label": "Distinct ID", "type": "person"},
            {"key": "$geoip_country_code", "label": "Country", "type": "event"},
            {"key": "$geoip_city_name", "label": "City", "type": "event"},
            {"key": "$browser", "label": "Browser", "type": "event"},
            {"key": "$os", "label": "Operating System", "type": "event"},
            {"key": "$device_type", "label": "Device Type", "type": "event"},
        ]

        return common_options