import logging
from typing import Any

import requests
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.feature_flag.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)


class FeatureFlagMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """API endpoints for feature flag migration from external providers"""

    @action(methods=["POST"], detail=False)
    def fetch_external_flags(self, request: Request) -> Response:
        """Fetch feature flags from external providers"""
        provider = request.data.get("provider")
        api_key = request.data.get("api_key")

        if not provider or not api_key:
            return Response({"error": "Provider and API key are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if provider == "amplitude":
                flags = self._fetch_amplitude_flags(api_key)
            else:
                return Response(
                    {"error": f"Provider '{provider}' is not supported yet"}, status=status.HTTP_400_BAD_REQUEST
                )

            # Filter flags to only show those with single conditions
            importable_flags = []
            non_importable_flags = []

            for flag in flags:
                if self._is_single_condition_flag(flag):
                    importable_flags.append({**flag, "importable": True, "import_issues": []})
                else:
                    non_importable_flags.append(
                        {**flag, "importable": False, "import_issues": ["Multiple conditions not supported yet"]}
                    )

            return Response(
                {
                    "importable_flags": importable_flags,
                    "non_importable_flags": non_importable_flags,
                    "total_flags": len(flags),
                    "importable_count": len(importable_flags),
                    "non_importable_count": len(non_importable_flags),
                }
            )

        except Exception as e:
            logger.exception(f"Error fetching flags from {provider}: {e}")
            return Response({"error": f"Failed to fetch flags: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(methods=["POST"], detail=False)
    def import_flags(self, request: Request) -> Response:
        """Import selected feature flags to PostHog"""
        provider = request.data.get("provider")
        selected_flags = request.data.get("selected_flags", [])
        field_mappings = request.data.get("field_mappings", {})

        if not provider or not selected_flags:
            return Response({"error": "Provider and selected flags are required"}, status=status.HTTP_400_BAD_REQUEST)

        imported_flags = []
        failed_imports = []

        for flag_data in selected_flags:
            try:
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

    def _fetch_amplitude_flags(self, api_key: str) -> list[dict[str, Any]]:
        """Fetch feature flags from Amplitude API"""
        # Note: This is a simplified implementation. In practice, you'd need to:
        # 1. Understand Amplitude's actual API structure for feature flags
        # 2. Handle pagination
        # 3. Handle different project/environment structures

        # For now, we'll simulate the API call structure
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        try:
            # This would be the actual Amplitude API endpoint
            # Note: The actual endpoint might be different - this is a placeholder
            response = requests.get(
                "https://amplitude.com/api/2/feature-flags",  # Placeholder URL
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                # Process Amplitude response format and convert to our standard format
                return self._normalize_amplitude_flags(data)
            else:
                raise Exception(f"Amplitude API returned status {response.status_code}: {response.text}")

        except requests.RequestException as e:
            raise Exception(f"Failed to connect to Amplitude API: {str(e)}")

    def _normalize_amplitude_flags(self, amplitude_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert Amplitude API response to normalized flag format"""
        # This is a placeholder implementation based on expected Amplitude structure
        # You would need to adjust this based on Amplitude's actual API response format

        flags = []
        flag_list = amplitude_data.get("feature_flags", [])

        for flag in flag_list:
            normalized_flag = {
                "key": flag.get("key", ""),
                "name": flag.get("name", flag.get("key", "")),
                "description": flag.get("description", ""),
                "enabled": flag.get("enabled", False),
                "conditions": self._extract_amplitude_conditions(flag),
                "variants": self._extract_amplitude_variants(flag),
                "metadata": {
                    "provider": "amplitude",
                    "original_id": flag.get("id"),
                    "created_at": flag.get("created_at"),
                    "updated_at": flag.get("updated_at"),
                },
            }
            flags.append(normalized_flag)

        return flags

    def _extract_amplitude_conditions(self, amplitude_flag: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract targeting conditions from Amplitude flag"""
        conditions = []

        # This is a placeholder - you'd need to understand Amplitude's condition structure
        targeting = amplitude_flag.get("targeting", {})
        rules = targeting.get("rules", [])

        for rule in rules:
            condition = {
                "properties": self._convert_amplitude_properties(rule.get("conditions", [])),
                "rollout_percentage": rule.get("rollout_percentage", 100),
                "variant": rule.get("variant"),
            }
            conditions.append(condition)

        return conditions

    def _extract_amplitude_variants(self, amplitude_flag: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract variants from Amplitude flag"""
        variants = []
        amplitude_variants = amplitude_flag.get("variants", [])

        for variant in amplitude_variants:
            variants.append(
                {
                    "key": variant.get("key", ""),
                    "name": variant.get("name", ""),
                    "rollout_percentage": variant.get("rollout_percentage", 0),
                    "value": variant.get("value"),
                }
            )

        return variants

    def _convert_amplitude_properties(self, amplitude_conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Amplitude conditions to PostHog property format"""
        properties = []

        for condition in amplitude_conditions:
            # This is a basic mapping - you'd need to handle all Amplitude condition types
            prop = {
                "key": condition.get("property", ""),
                "operator": self._map_amplitude_operator(condition.get("operator", "")),
                "value": condition.get("value", ""),
                "type": "person",  # Assuming person properties for now
            }
            properties.append(prop)

        return properties

    def _map_amplitude_operator(self, amplitude_operator: str) -> str:
        """Map Amplitude operators to PostHog operators"""
        operator_mapping = {
            "equals": "exact",
            "not_equals": "not_equal",
            "contains": "icontains",
            "not_contains": "not_icontains",
            "greater_than": "gt",
            "less_than": "lt",
            "greater_than_or_equal": "gte",
            "less_than_or_equal": "lte",
        }
        return operator_mapping.get(amplitude_operator, "exact")

    def _is_single_condition_flag(self, flag: dict[str, Any]) -> bool:
        """Check if flag has only single condition (importable)"""
        conditions = flag.get("conditions", [])
        return len(conditions) <= 1

    def _convert_to_posthog_format(
        self, external_flag: dict[str, Any], field_mappings: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert external flag format to PostHog FeatureFlag format"""
        # Apply field mappings if provided
        key = field_mappings.get("key", external_flag.get("key", ""))
        name = field_mappings.get("name", external_flag.get("name", external_flag.get("key", "")))

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
