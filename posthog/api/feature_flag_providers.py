"""
External provider system for feature flag import.

This module contains all provider implementations in a single file for simplicity.
Each provider is implemented as a separate class that inherits from BaseProvider.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import requests
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Base exception for provider-related errors."""
    pass


class RateLimitError(ProviderError):
    """Exception raised when API rate limit is exceeded."""
    pass


class AuthenticationError(ProviderError):
    """Exception raised when authentication fails."""
    pass


class FieldInfo:
    """Information about a field extracted from an external flag."""

    def __init__(self, field_type: str, key: str, display_name: str):
        self.field_type = field_type
        self.key = key
        self.display_name = display_name

    def __hash__(self):
        return hash((self.field_type, self.key, self.display_name))

    def __eq__(self, other):
        if not isinstance(other, FieldInfo):
            return False
        return (self.field_type, self.key, self.display_name) == (other.field_type, other.key, other.display_name)

    def to_dict(self):
        return {
            "type": self.field_type,
            "external_key": self.key,
            "display_name": self.display_name,
        }


class BaseProvider(ABC):
    """Abstract base class for external feature flag providers."""

    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider."""
        pass

    @abstractmethod
    def fetch_flags(self, api_key: str, project_key: Optional[str] = None, environment: str = "production") -> Response:
        """
        Fetch feature flags from the external provider.

        Args:
            api_key: API key for authentication
            project_key: Project identifier (optional, provider-specific)
            environment: Environment name (optional, defaults to production)

        Returns:
            Response object with flag data or error
        """
        pass

    @abstractmethod
    def extract_fields_from_flag(self, flag: Dict[str, Any]) -> List[FieldInfo]:
        """
        Extract field information from a single flag.

        Args:
            flag: Flag data from the external provider

        Returns:
            List of FieldInfo objects representing fields used in the flag
        """
        pass

    def extract_field_info_from_property(self, prop: Dict[str, Any]) -> Optional[FieldInfo]:
        """
        Extract field information from a property.

        This is a fallback method for generic property handling.
        Providers can override this for custom behavior.

        Args:
            prop: Property data

        Returns:
            FieldInfo object or None if property should be ignored
        """
        prop_key = prop.get("key", "")
        if prop_key and prop.get("type") != "cohort":
            return FieldInfo(
                field_type="custom",
                key=prop_key,
                display_name=f"Custom Field: {prop_key.replace('_', ' ').title()}"
            )
        return None

    def get_external_key_from_property(self, prop: Dict[str, Any]) -> Optional[str]:
        """
        Extract the external key from a property.

        This is used for validation and field mapping.
        Providers can override this for custom behavior.

        Args:
            prop: Property data

        Returns:
            External key string or None
        """
        return prop.get("key")

    def get_display_name(self) -> str:
        """Get the display name for this provider."""
        return self.provider_name.title()


class StatsigProvider(BaseProvider):
    """Statsig provider implementation."""

    @property
    def provider_name(self) -> str:
        return "statsig"

    def fetch_flags(self, api_key: str, project_key: Optional[str] = None, environment: str = "production") -> Response:
        """Fetch both feature gates and dynamic configs from Statsig API."""
        headers = {"STATSIG-API-KEY": api_key, "STATSIG-API-VERSION": "20240601", "Content-Type": "application/json"}
        all_flags = []

        try:
            # Fetch Feature Gates
            gates_endpoint = "https://statsigapi.net/console/v1/gates"
            logger.info(f"Statsig: Fetching feature gates from {gates_endpoint}")
            gates_response = requests.get(gates_endpoint, headers=headers, timeout=30)

            if gates_response.status_code == 401:
                raise AuthenticationError("Invalid API key. Please check your Statsig Console API Key.")
            elif gates_response.status_code == 403:
                raise AuthenticationError("Access denied. Please ensure your API key has the required permissions.")
            elif gates_response.status_code == 429:
                raise RateLimitError("Statsig API rate limit exceeded. Please try again later.")
            elif gates_response.status_code != 200:
                return Response(
                    {"error": f"Failed to fetch feature gates: {gates_response.status_code} {gates_response.reason}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            gates_data = gates_response.json()
            logger.info(f"Statsig: Found {len(gates_data.get('data', []))} feature gates")

            # Transform feature gates
            for gate in gates_data.get("data", []):
                transformed_flag = self._transform_statsig_flag(gate, "feature_gate")
                all_flags.append(transformed_flag)

            # Fetch Dynamic Configs
            configs_endpoint = "https://statsigapi.net/console/v1/dynamic_configs"
            logger.info(f"Statsig: Fetching dynamic configs from {configs_endpoint}")
            configs_response = requests.get(configs_endpoint, headers=headers, timeout=30)

            if configs_response.status_code == 200:
                configs_data = configs_response.json()
                logger.info(f"Statsig: Found {len(configs_data.get('data', []))} dynamic configs")

                # Transform dynamic configs
                for config in configs_data.get("data", []):
                    transformed_flag = self._transform_statsig_flag(config, "dynamic_config")
                    all_flags.append(transformed_flag)

        except (AuthenticationError, RateLimitError) as e:
            error_status = status.HTTP_401_UNAUTHORIZED if isinstance(e, AuthenticationError) else status.HTTP_429_TOO_MANY_REQUESTS
            return Response({"error": str(e)}, status=error_status)
        except Exception as e:
            logger.exception(f"Error fetching Statsig flags: {e}")
            return Response(
                {"error": f"Failed to fetch flags: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Filter flags to only show those with single conditions
        importable_flags = []
        non_importable_flags = []

        for flag in all_flags:
            if self._is_single_condition_flag(flag):
                importable_flags.append({**flag, "importable": True, "import_issues": []})
            else:
                non_importable_flags.append(
                    {**flag, "importable": False, "import_issues": ["Multiple conditions not supported yet"]}
                )

        return Response({
            "importable_flags": importable_flags,
            "non_importable_flags": non_importable_flags,
            "total_flags": len(all_flags),
            "importable_count": len(importable_flags),
            "non_importable_count": len(non_importable_flags),
        })

    def extract_fields_from_flag(self, flag: Dict[str, Any]) -> List[FieldInfo]:
        """Extract actual criteria fields from Statsig flag metadata."""
        flag_key = flag.get("key", "unknown")
        logger.info(f"DEBUG: Extracting fields from Statsig flag: {flag_key}")

        field_infos = []

        # Get the original metadata
        metadata = flag.get("metadata", {})

        # Look for rules in the original response
        rules = metadata.get("rules", [])

        for rule_idx, rule in enumerate(rules):
            logger.info(f"DEBUG: Processing rule {rule_idx} for flag {flag_key}: {rule}")

            # Get conditions from the rule
            conditions = rule.get("conditions", [])

            for condition_idx, condition in enumerate(conditions):
                logger.info(f"DEBUG: Processing condition {condition_idx} in rule {rule_idx}: {condition}")

                # Extract field from condition
                field_info = self._extract_field_from_statsig_condition(condition)
                if field_info:
                    field_infos.append(field_info)
                    logger.info(f"DEBUG: Added field from condition: {field_info.to_dict()}")

        logger.info(f"DEBUG: Flag {flag_key} extracted {len(field_infos)} fields")
        return field_infos

    def extract_field_info_from_property(self, prop: Dict[str, Any]) -> Optional[FieldInfo]:
        """Extract field information from a Statsig property."""
        # Statsig-specific property handling
        prop_key = prop.get("key", "")
        prop_type = prop.get("type", "")

        if not prop_key or prop_type == "cohort":
            return None

        # Determine if this is a built-in field
        built_in_fields = {
            "email", "user_id", "country", "region", "city", "ip",
            "browser_name", "browser_version", "os_name", "os_version",
            "device", "device_model"
        }

        if prop_key.lower() in built_in_fields:
            field_type = "built_in"
        elif prop_type == "segment":
            field_type = "segment"
        else:
            field_type = "custom"

        display_name = prop_key.replace("_", " ").title()

        return FieldInfo(
            field_type=field_type,
            key=prop_key,
            display_name=display_name
        )

    def _transform_statsig_flag(self, flag_data: Dict[str, Any], statsig_type: str) -> Dict[str, Any]:
        """Transform Statsig flag format to common format."""
        # Basic flag information
        transformed = {
            "key": flag_data.get("id", ""),
            "name": flag_data.get("name", flag_data.get("id", "")),
            "description": flag_data.get("description", ""),
            "enabled": flag_data.get("isEnabled", True),
            "conditions": [],
            "variants": [],
            "metadata": {
                "statsig_type": statsig_type,
                "original": flag_data,
                "rules": flag_data.get("rules", [])
            }
        }

        # Transform rules to conditions
        rules = flag_data.get("rules", [])
        for rule in rules:
            condition = self._transform_statsig_rule_to_condition(rule)
            if condition:
                transformed["conditions"].append(condition)

        return transformed

    def _transform_statsig_rule_to_condition(self, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a Statsig rule to a condition."""
        conditions = rule.get("conditions", [])
        if not conditions:
            return None

        properties = []
        for condition in conditions:
            prop = self._transform_statsig_condition_to_property(condition)
            if prop:
                properties.append(prop)

        return {
            "properties": properties,
            "rollout_percentage": rule.get("passPercentage", 100),
        }

    def _transform_statsig_condition_to_property(self, condition: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a Statsig condition to a property."""
        field = condition.get("field", "")
        operator = condition.get("operator", "")
        target_value = condition.get("targetValue")

        if not field:
            return None

        # Map Statsig operators to PostHog operators
        operator_mapping = {
            "eq": "exact",
            "neq": "is_not",
            "lt": "lt",
            "lte": "lte",
            "gt": "gt",
            "gte": "gte",
            "contains": "icontains",
            "not_contains": "not_icontains",
            "in": "exact",
            "not_in": "is_not"
        }

        posthog_operator = operator_mapping.get(operator, "exact")

        return {
            "key": field,
            "value": target_value,
            "operator": posthog_operator,
            "type": "person"
        }

    def _extract_field_from_statsig_condition(self, condition: Dict[str, Any]) -> Optional[FieldInfo]:
        """Extract field information from a Statsig condition."""
        field = condition.get("field", "")
        if not field:
            return None

        # Determine field type
        built_in_fields = {
            "email", "user_id", "country", "region", "city", "ip",
            "browser_name", "browser_version", "os_name", "os_version",
            "device", "device_model"
        }

        if field.lower() in built_in_fields:
            field_type = "built_in"
        else:
            field_type = "custom"

        display_name = field.replace("_", " ").title()

        return FieldInfo(
            field_type=field_type,
            key=field,
            display_name=display_name
        )

    def _is_single_condition_flag(self, flag: Dict[str, Any]) -> bool:
        """Check if flag has only single condition (importable)."""
        conditions = flag.get("conditions", [])
        return len(conditions) <= 1


class LaunchDarklyProvider(BaseProvider):
    """LaunchDarkly provider implementation."""

    @property
    def provider_name(self) -> str:
        return "launchdarkly"

    def fetch_flags(self, api_key: str, project_key: Optional[str] = None, environment: str = "production") -> Response:
        """Fetch flags from LaunchDarkly API."""
        if not project_key:
            project_key = "default"

        headers = {"Authorization": api_key, "LD-API-Version": "20240415", "Content-Type": "application/json"}

        try:
            # Step 1: Get all feature flags for the project
            list_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}"

            if self.rate_limiter:
                response, success = self.rate_limiter.make_request_with_rate_limiting(list_endpoint, headers)
                if not success:
                    if response.status_code == 429:
                        raise RateLimitError("LaunchDarkly API rate limit exceeded. Please try again later.")
                    else:
                        return Response(
                            {"error": f"Failed to fetch flags list: {response.status_code} {response.reason}"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
            else:
                # Fallback to direct requests if no rate limiter is available
                response = requests.get(list_endpoint, headers=headers, timeout=30)
                success = response.status_code == 200

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key. Please check your LaunchDarkly API key.")
            elif response.status_code == 403:
                raise AuthenticationError("Access denied. Please ensure your API key has the required permissions.")
            elif response.status_code == 404:
                return Response(
                    {"error": f"Project '{project_key}' not found. Please check your project key."},
                    status=status.HTTP_404_NOT_FOUND
                )
            elif response.status_code != 200:
                return Response(
                    {"error": f"Failed to fetch flags: {response.status_code} {response.reason}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            flags_data = response.json()
            flags = flags_data.get("items", [])

        except (AuthenticationError, RateLimitError) as e:
            error_status = status.HTTP_401_UNAUTHORIZED if isinstance(e, AuthenticationError) else status.HTTP_429_TOO_MANY_REQUESTS
            return Response({"error": str(e)}, status=error_status)
        except Exception as e:
            logger.exception(f"Error fetching LaunchDarkly flags: {e}")
            return Response(
                {"error": f"Failed to fetch flags: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Step 2: For each flag, get detailed information including rules
        all_flags = []
        for flag in flags:
            flag_key = flag.get("key", "")
            if not flag_key:
                continue

            # Get detailed flag information
            detail_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}/{flag_key}"

            if self.rate_limiter:
                detail_response, detail_success = self.rate_limiter.make_request_with_rate_limiting(detail_endpoint, headers)
            else:
                detail_response = requests.get(detail_endpoint, headers=headers, timeout=30)
                detail_success = detail_response.status_code == 200

            if detail_success and detail_response.status_code == 200:
                detailed_flag = detail_response.json()
                transformed_flag = self._transform_launchdarkly_flag(detailed_flag, environment)
                all_flags.append(transformed_flag)
            else:
                # Fallback to basic flag info if detailed fetch fails
                transformed_flag = self._transform_launchdarkly_flag(flag, environment)
                all_flags.append(transformed_flag)

        # Filter flags to only show those with single conditions
        importable_flags = []
        non_importable_flags = []

        for flag in all_flags:
            if self._is_single_condition_flag(flag):
                importable_flags.append({**flag, "importable": True, "import_issues": []})
            else:
                non_importable_flags.append(
                    {**flag, "importable": False, "import_issues": ["Multiple conditions not supported yet"]}
                )

        return Response({
            "importable_flags": importable_flags,
            "non_importable_flags": non_importable_flags,
            "total_flags": len(all_flags),
            "importable_count": len(importable_flags),
            "non_importable_count": len(non_importable_flags),
        })

    def extract_fields_from_flag(self, flag: Dict[str, Any]) -> List[FieldInfo]:
        """Extract actual criteria fields from LaunchDarkly flag metadata."""
        flag_key = flag.get("key", "unknown")
        logger.info(f"DEBUG: Extracting fields from LaunchDarkly flag: {flag_key}")

        field_infos = []

        # Get the original metadata
        metadata = flag.get("metadata", {})
        environments = metadata.get("environments", {})

        # Look for rules in each environment
        for env_name, env_data in environments.items():
            rules = env_data.get("rules", [])

            for rule_idx, rule in enumerate(rules):
                logger.info(f"DEBUG: Processing rule {rule_idx} for flag {flag_key} in environment {env_name}: {rule}")

                # Get clauses from the rule
                clauses = rule.get("clauses", [])

                for clause_idx, clause in enumerate(clauses):
                    logger.info(f"DEBUG: Processing clause {clause_idx} in rule {rule_idx}: {clause}")

                    # Extract field from clause
                    field_info = self._extract_field_from_launchdarkly_clause(clause)
                    if field_info:
                        field_infos.append(field_info)
                        logger.info(f"DEBUG: Added field from clause: {field_info.to_dict()}")

        logger.info(f"DEBUG: Flag {flag_key} extracted {len(field_infos)} fields")
        return field_infos

    def extract_field_info_from_property(self, prop: Dict[str, Any]) -> Optional[FieldInfo]:
        """Extract field information from a LaunchDarkly property."""
        # LaunchDarkly-specific property handling
        prop_key = prop.get("key", "")
        prop_type = prop.get("type", "")

        if not prop_key or prop_type == "cohort":
            return None

        # Determine if this is a built-in field
        built_in_fields = {
            "email", "user_id", "country", "region", "city", "ip",
            "browser_name", "browser_version", "os_name", "os_version",
            "device", "device_model", "key"  # LaunchDarkly uses "key" for user ID
        }

        if prop_key.lower() in built_in_fields:
            field_type = "built_in"
        elif prop_type == "segment":
            field_type = "segment"
        else:
            field_type = "custom"

        display_name = prop_key.replace("_", " ").title()

        return FieldInfo(
            field_type=field_type,
            key=prop_key,
            display_name=display_name
        )

    def _transform_launchdarkly_flag(self, flag_data: Dict[str, Any], environment: str) -> Dict[str, Any]:
        """Transform LaunchDarkly flag format to common format."""
        # Basic flag information
        transformed = {
            "key": flag_data.get("key", ""),
            "name": flag_data.get("name", flag_data.get("key", "")),
            "description": flag_data.get("description", ""),
            "enabled": False,  # Will be set based on environment
            "conditions": [],
            "variants": [],
            "metadata": {
                "original": flag_data,
                "environments": flag_data.get("environments", {})
            }
        }

        # Get environment-specific data
        environments = flag_data.get("environments", {})
        env_data = environments.get(environment, {})

        if env_data:
            transformed["enabled"] = env_data.get("on", False)

            # Transform rules to conditions
            rules = env_data.get("rules", [])
            for rule in rules:
                condition = self._transform_launchdarkly_rule_to_condition(rule)
                if condition:
                    transformed["conditions"].append(condition)

            # Handle variants
            variations = flag_data.get("variations", [])
            if len(variations) > 1:
                transformed["variants"] = [
                    {"key": str(i), "name": var.get("name", f"Variant {i}"), "value": var.get("value")}
                    for i, var in enumerate(variations)
                ]

        return transformed

    def _transform_launchdarkly_rule_to_condition(self, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a LaunchDarkly rule to a condition."""
        clauses = rule.get("clauses", [])
        if not clauses:
            return None

        properties = []
        for clause in clauses:
            prop = self._transform_launchdarkly_clause_to_property(clause)
            if prop:
                properties.append(prop)

        # LaunchDarkly uses "rollout" for percentage-based rules
        rollout = rule.get("rollout", {})
        rollout_percentage = 100

        if rollout:
            # For bucket-based rollouts, calculate percentage
            variations = rollout.get("variations", [])
            if variations and len(variations) > 0:
                # Sum up all the weights to get total percentage
                total_weight = sum(var.get("weight", 0) for var in variations) / 1000  # LaunchDarkly uses weights in thousandths
                rollout_percentage = min(100, total_weight)

        return {
            "properties": properties,
            "rollout_percentage": rollout_percentage,
        }

    def _transform_launchdarkly_clause_to_property(self, clause: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Transform a LaunchDarkly clause to a property."""
        attribute = clause.get("attribute", "")
        operator = clause.get("op", "")
        values = clause.get("values", [])

        if not attribute:
            return None

        # Map LaunchDarkly operators to PostHog operators
        operator_mapping = {
            "in": "exact",
            "endsWith": "iregex",
            "startsWith": "iregex",
            "matches": "iregex",
            "contains": "icontains",
            "lessThan": "lt",
            "lessThanOrEqual": "lte",
            "greaterThan": "gt",
            "greaterThanOrEqual": "gte",
            "before": "lt",
            "after": "gt",
            "segmentMatch": "exact",  # Will be handled specially
            "exists": "is_set"
        }

        posthog_operator = operator_mapping.get(operator, "exact")

        # Handle different value formats
        if len(values) == 1:
            value = values[0]
        elif len(values) > 1:
            value = values  # Multiple values
        else:
            value = True if operator == "exists" else ""

        return {
            "key": attribute,
            "value": value,
            "operator": posthog_operator,
            "type": "person"
        }

    def _extract_field_from_launchdarkly_clause(self, clause: Dict[str, Any]) -> Optional[FieldInfo]:
        """Extract field information from a LaunchDarkly clause."""
        attribute = clause.get("attribute", "")
        if not attribute:
            return None

        # Determine field type
        built_in_fields = {
            "email", "user_id", "country", "region", "city", "ip",
            "browser_name", "browser_version", "os_name", "os_version",
            "device", "device_model", "key"  # LaunchDarkly uses "key" for user ID
        }

        if attribute.lower() in built_in_fields:
            field_type = "built_in"
        elif clause.get("op") == "segmentMatch":
            field_type = "segment"
        else:
            field_type = "custom"

        display_name = attribute.replace("_", " ").title()

        return FieldInfo(
            field_type=field_type,
            key=attribute,
            display_name=display_name
        )

    def _is_single_condition_flag(self, flag: Dict[str, Any]) -> bool:
        """Check if flag has only single condition (importable)."""
        conditions = flag.get("conditions", [])
        return len(conditions) <= 1


class ProviderRegistry:
    """Registry for managing external feature flag providers."""

    def __init__(self):
        self._providers: Dict[str, type] = {}
        self._register_default_providers()

    def _register_default_providers(self):
        """Register the default providers."""
        self.register("statsig", StatsigProvider)
        self.register("launchdarkly", LaunchDarklyProvider)

    def register(self, name: str, provider_class: type):
        """
        Register a provider class.

        Args:
            name: Provider name identifier
            provider_class: Provider class that inherits from BaseProvider
        """
        if not issubclass(provider_class, BaseProvider):
            raise ValueError(f"Provider class {provider_class} must inherit from BaseProvider")

        self._providers[name] = provider_class
        logger.info(f"Registered provider: {name} -> {provider_class.__name__}")

    def get_provider(self, name: str, **kwargs) -> Optional[BaseProvider]:
        """
        Get an instance of a provider by name.

        Args:
            name: Provider name identifier
            **kwargs: Additional arguments to pass to provider constructor

        Returns:
            Provider instance or None if not found
        """
        provider_class = self._providers.get(name)
        if provider_class:
            return provider_class(**kwargs)
        return None

    def list_providers(self) -> Dict[str, str]:
        """
        List all registered providers.

        Returns:
            Dictionary mapping provider names to class names
        """
        return {name: cls.__name__ for name, cls in self._providers.items()}

    def is_supported(self, name: str) -> bool:
        """
        Check if a provider is supported.

        Args:
            name: Provider name identifier

        Returns:
            True if provider is supported, False otherwise
        """
        return name in self._providers


# Global provider registry instance
provider_registry = ProviderRegistry()