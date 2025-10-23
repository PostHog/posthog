import time
import random
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = logging.getLogger(__name__)

PROVIDER_LAUNCHDARKLY = "launchdarkly"
PROVIDER_STATSIG = "statsig"


class ExternalFieldMappingDict(TypedDict):
    external_key: str
    external_type: str
    display_name: str
    posthog_field: str | None
    auto_selected: bool


class PropertyDict(TypedDict, total=False):
    key: str
    external_key: str
    operator: str
    value: Any
    type: str


class ConditionDict(TypedDict, total=False):
    properties: list[PropertyDict]
    rollout_percentage: int
    variant: str | None
    rule_id: str


class VariantDict(TypedDict, total=False):
    key: str
    name: str
    rollout_percentage: int
    value: Any
    description: str
    is_default: bool


class FieldInfoDict(TypedDict, total=False):
    external_key: str
    key: str
    type: str
    values: list[Any]
    description: str
    display_name: str


class FlagMetadataDict(TypedDict, total=False):
    provider: str
    original_id: str
    created_at: str | None
    updated_at: str | None
    raw_environments: dict[str, Any]
    api_key: str | None
    project_key: str | None
    # Statsig-specific
    statsig_type: str
    creator: str | None
    last_modifier: str | None
    original_rules: list[dict[str, Any]]
    # LaunchDarkly-specific
    environments: dict[str, Any]
    tags: list[str]
    total_rules: int
    has_prerequisites: bool
    environment_configs: dict[str, Any]
    raw_variations: list[dict[str, Any]]
    raw_key: str
    debug_raw_flag_keys: list[str]


class TransformedFlagDict(TypedDict, total=False):
    key: str
    name: str
    description: str
    enabled: bool
    conditions: list[ConditionDict]
    variants: list[VariantDict]
    metadata: FlagMetadataDict
    rollout_percentage: int
    importable: bool
    non_importable_reason: str | None
    import_issues: list[str]


class FieldMappingDict(TypedDict):
    posthog_field: str
    posthog_type: str


class ErrorResult(TypedDict):
    error: str
    status: int


class FetchFlagsSuccessResult(TypedDict):
    importable_flags: list[TransformedFlagDict]
    non_importable_flags: list[TransformedFlagDict]
    total_flags: int
    importable_count: int
    non_importable_count: int


class ExternalUniqueFieldDict(TypedDict):
    type: str
    external_key: str
    display_name: str


class PostHogVariantDict(TypedDict):
    key: str
    name: str
    rollout_percentage: int


class GroupDict(TypedDict, total=False):
    properties: list[PropertyDict]
    rollout_percentage: int
    variant: str | None


class FiltersDict(TypedDict, total=False):
    groups: list[GroupDict]
    payloads: dict[str, str | None]
    multivariate: "MultivariateConfigDict | None"


class MultivariateConfigDict(TypedDict, total=False):
    variants: list[PostHogVariantDict]
    payloads: dict[str, Any]


class MultivariateFiltersResult(TypedDict, total=False):
    multivariate: MultivariateConfigDict
    payloads: dict[str, str | None]


class ImportedFlagDict(TypedDict):
    id: int
    key: str
    name: str
    active: bool


class ImportedFlagResult(TypedDict):
    external_flag: dict[str, Any]
    posthog_flag: ImportedFlagDict


class FailedImportResult(TypedDict):
    flag: dict[str, Any]
    error: str


class ImportFlagsResult(TypedDict):
    imported_flags: list[ImportedFlagResult]
    failed_imports: list[FailedImportResult]
    success_count: int
    failure_count: int


class PostHogFlagFormatDict(TypedDict):
    key: str
    name: str
    filters: FiltersDict
    active: bool


class RolloutVariationDict(TypedDict):
    variation: int | None
    weight: int
    percentage: int


class RolloutInfoDict(TypedDict):
    type: str
    variations: list[RolloutVariationDict]


class DirectVariationInfoDict(TypedDict):
    type: str
    variation: int | None


class ClauseInfoDict(TypedDict):
    attribute: str
    operator: str
    values: list[Any]
    negate: bool
    context_kind: str


class RuleInfoDict(TypedDict):
    id: str
    description: str
    clauses: list[ClauseInfoDict]
    rollout_info: RolloutInfoDict | DirectVariationInfoDict | None


class EnvironmentDataDict(TypedDict):
    enabled: bool
    rules_count: int
    has_targets: bool
    target_count: int
    detailed_rules: list[RuleInfoDict]
    fallthrough: RolloutInfoDict | DirectVariationInfoDict | None
    off_variation: int | None


class BaseImporter(ABC):
    @abstractmethod
    def fetch_flags(self, api_key: str, project_key: str | None = None) -> list[dict[str, Any]] | ErrorResult:
        pass

    @abstractmethod
    def transform_flag_for_response(
        self,
        raw_flag: dict[str, Any],
        environment: str = "production",
        api_key: str | None = None,
        project_key: str | None = None,
    ) -> TransformedFlagDict:
        pass

    @abstractmethod
    def extract_fields_from_external_flag(self, flag: dict[str, Any]) -> list[FieldInfoDict]:
        pass

    @abstractmethod
    def extract_field_info(self, prop: PropertyDict) -> FieldInfoDict | None:
        pass

    @abstractmethod
    def extract_enabled_state(self, external_flag: dict[str, Any], environment: str) -> bool:
        """Extract the enabled state from external flag"""
        pass

    @abstractmethod
    def build_multivariate_filters(
        self, external_flag: dict[str, Any], variants: list[VariantDict], environment: str
    ) -> MultivariateFiltersResult | None:
        """Build multivariate filters for the flag"""
        pass

    @abstractmethod
    def extract_conditions(
        self, external_flag: dict[str, Any], environment: str, team: "Team | None"
    ) -> list[ConditionDict]:
        """Extract conditions from external flag"""
        pass

    @abstractmethod
    def get_external_key_from_property(self, prop: PropertyDict) -> str | None:
        """Extract the external field key from a property"""
        pass

    def _is_valid_variant_key(self, variant_key: str) -> bool:
        """Check if variant key contains only letters, numbers, hyphens, and underscores"""
        import re

        return bool(re.match(r"^[a-zA-Z0-9_-]+$", variant_key))


class ExternalProvidersImporter:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.launchdarkly_importer = LaunchDarklyImporter()
        self.statsig_importer = StatsigImporter()

    def fetch_and_transform_flags(
        self, provider: str, api_key: str, params: dict[str, Any] | None = None
    ) -> FetchFlagsSuccessResult | ErrorResult:
        """
        Fetch and transform flags from external providers.

        Args:
            provider: The external provider name (e.g., "launchdarkly", "statsig")
            api_key: API key for the provider
            params: Dictionary of provider-specific parameters:
                - For LaunchDarkly: {"environment": "production", "project_key": "default"}
                - For Statsig: {} (no additional params currently needed)

        Returns:
            Dictionary with importable_flags, non_importable_flags, and counts,
            or error dictionary with 'error' and 'status' keys
        """
        if params is None:
            params = {}

        try:
            if provider == PROVIDER_LAUNCHDARKLY:
                environment = params.get("environment", "production")
                project_key = params.get("project_key", "default")
                external_flags = self.launchdarkly_importer.fetch_flags(api_key, project_key)

                # Check if result is an error
                if isinstance(external_flags, dict) and "error" in external_flags and "status" in external_flags:
                    return external_flags

                transformed_flags = []
                for flag in external_flags:
                    try:
                        transformed_flag = self.launchdarkly_importer.transform_flag_for_response(
                            flag, environment, api_key, project_key
                        )
                        transformed_flags.append(transformed_flag)
                    except Exception as e:
                        logger.exception(
                            f"Failed to transform LaunchDarkly flag {flag.get('key', 'unknown')}: {str(e)}"
                        )

            elif provider == PROVIDER_STATSIG:
                external_flags = self.statsig_importer.fetch_flags(api_key)

                # Check if result is an error
                if isinstance(external_flags, dict) and "error" in external_flags and "status" in external_flags:
                    return external_flags

                transformed_flags = []
                for flag in external_flags:
                    try:
                        transformed_flag = self.statsig_importer.transform_flag_for_response(flag)
                        transformed_flags.append(transformed_flag)
                    except Exception as e:
                        logger.exception(f"Failed to transform Statsig flag {flag.get('key', 'unknown')}: {str(e)}")

            else:
                return {
                    "error": f"Provider {provider} is not supported. Supported providers: launchdarkly, statsig",
                    "status": 400,
                }

            # Separate importable and non-importable flags
            importable_flags = [flag for flag in transformed_flags if flag["importable"]]
            non_importable_flags = [flag for flag in transformed_flags if not flag["importable"]]

            return {
                "importable_flags": importable_flags,
                "non_importable_flags": non_importable_flags,
                "total_flags": len(transformed_flags),
                "importable_count": len(importable_flags),
                "non_importable_count": len(non_importable_flags),
            }

        except Exception as e:
            logger.exception(f"Failed to fetch flags from {provider}: {str(e)}")
            return {"error": f"Failed to fetch flags from {provider} due to an internal error.", "status": 500}

    def extract_unique_fields_from_flags(
        self, selected_flags: list[dict[str, Any]], provider: str
    ) -> list[ExternalUniqueFieldDict]:
        """Extract unique fields from selected flags' rules for field mapping"""
        unique_fields = set()
        provider_importer = self._get_provider_importer(provider)

        for _flag_idx, flag in enumerate(selected_flags):
            field_info_list = provider_importer.extract_fields_from_external_flag(flag)
            for field_info in field_info_list:
                if field_info:
                    unique_fields.add((field_info["type"], field_info["key"], field_info["display_name"]))

        deduplicated_fields = {}
        for field_type, field_key, display_name in sorted(unique_fields):
            if field_key not in deduplicated_fields:
                deduplicated_fields[field_key] = (field_type, field_key, display_name)

        result: list[ExternalUniqueFieldDict] = [
            {"type": field_type, "external_key": field_key, "display_name": display_name}
            for field_type, field_key, display_name in sorted(deduplicated_fields.values())
        ]
        return result

    def create_field_mapping_suggestions(
        self, unique_fields: list[ExternalUniqueFieldDict]
    ) -> list[ExternalFieldMappingDict]:
        """Create field mapping suggestions with default mappings for known fields"""
        field_mappings: list[ExternalFieldMappingDict] = []

        for field in unique_fields:
            external_key = field["external_key"]
            field_type = field["type"]
            display_name = field["display_name"]

            default_posthog_field = self._get_default_posthog_mapping(field_type, external_key)
            auto_selected = default_posthog_field is not None

            mapping: ExternalFieldMappingDict = {
                "external_key": external_key,
                "external_type": field_type,
                "display_name": display_name,
                "posthog_field": default_posthog_field,
                "auto_selected": auto_selected,
            }

            field_mappings.append(mapping)

        return field_mappings

    def import_flags(
        self,
        provider: str,
        selected_flags: list[dict[str, Any]],
        environment: str,
        field_mappings: dict[str, FieldMappingDict],
        team: "Team",
        user: "User",
    ) -> ImportFlagsResult:
        """
        Import selected feature flags from external providers to PostHog.

        Args:
            provider: The external provider name (e.g., "launchdarkly", "statsig")
            selected_flags: List of flag data to import
            environment: Environment name for LaunchDarkly flags
            field_mappings: Dictionary mapping external fields to PostHog properties
            team: The PostHog team to import flags into
            user: The user creating the flags

        Returns:
            Dictionary with imported_flags, failed_imports, and counts
        """
        from posthog.models import FeatureFlag

        imported_flags: list[ImportedFlagResult] = []
        failed_imports: list[FailedImportResult] = []

        for flag_data in selected_flags:
            try:
                if provider == PROVIDER_LAUNCHDARKLY:
                    raw_environments = flag_data.get("metadata", {}).get("raw_environments")
                    if raw_environments:
                        mock_flag = {"key": flag_data.get("key", ""), "environments": raw_environments}
                        is_importable, import_issues = self.launchdarkly_importer.check_flag_importable(
                            mock_flag, environment
                        )
                        if not is_importable:
                            error_msg = (
                                f"Flag is not importable: {', '.join(import_issues)}"
                                if import_issues
                                else "Flag is not importable for environment '{environment}'"
                            )
                            failed_imports.append({"flag": flag_data, "error": error_msg})
                            continue
                elif provider == PROVIDER_STATSIG:
                    if not flag_data.get("importable", True):
                        import_issues = flag_data.get("import_issues", ["Unknown issue"])
                        failed_imports.append(
                            {"flag": flag_data, "error": f"Flag is not importable: {', '.join(import_issues)}"}
                        )
                        continue

                is_valid, validation_error = self._validate_flag_field_mappings(flag_data, field_mappings, provider)  # type: ignore[arg-type]
                if not is_valid:
                    failed_imports.append({"flag": flag_data, "error": validation_error or "Validation failed"})
                    continue

                # Generate unique flag key (only adds suffix if there's a conflict)
                original_flag_key = flag_data.get("key", "")
                unique_flag_key = self._generate_unique_flag_key(original_flag_key, team)

                flag_data_with_unique_key = flag_data.copy()
                flag_data_with_unique_key["key"] = unique_flag_key

                posthog_flag_data = self._convert_external_flag_to_posthog_format(
                    flag_data_with_unique_key, provider, environment, field_mappings, team
                )

                new_flag = FeatureFlag.objects.create(
                    team=team,
                    created_by=user,
                    last_modified_by=user,
                    version=1,
                    **posthog_flag_data,
                )

                import_result: ImportedFlagResult = {
                    "external_flag": flag_data,
                    "posthog_flag": {
                        "id": new_flag.id,
                        "key": new_flag.key,
                        "name": new_flag.name,
                        "active": new_flag.active,
                    },
                }

                imported_flags.append(import_result)

            except Exception as e:
                logger.exception(f"Failed to import flag: {str(e)}")
                failed_imports.append(
                    {"flag": flag_data, "error": "Failed to import flag: an internal error occurred."}
                )

        return {
            "imported_flags": imported_flags,
            "failed_imports": failed_imports,
            "success_count": len(imported_flags),
            "failure_count": len(failed_imports),
        }

    def _get_provider_importer(self, provider: str) -> BaseImporter:
        """Get the appropriate provider importer instance"""
        if provider == PROVIDER_LAUNCHDARKLY:
            return self.launchdarkly_importer
        elif provider == PROVIDER_STATSIG:
            return self.statsig_importer
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _get_default_posthog_mapping(self, field_type: str, external_key: str) -> str | None:
        """Get default PostHog field mapping for known field keys"""
        mapping = {"email": "email", "user_id": "distinct_id", "distinct_id": "distinct_id"}
        return mapping.get(external_key.lower())

    def _build_groups_from_conditions(
        self,
        conditions: list[ConditionDict],
        field_mappings: dict[str, FieldMappingDict] | None,
        provider: str,
        has_variants: bool,
    ) -> list[GroupDict]:
        """Build PostHog groups from transformed conditions"""
        groups: list[GroupDict] = []

        for condition in conditions:
            properties = condition.get("properties", [])

            # Apply field mappings to properties if provided
            if field_mappings:
                properties = self._apply_field_mappings_to_properties(properties, field_mappings, provider)

            # Validate properties have supported types (person, cohort, flag)
            valid_properties = []
            for prop in properties:
                prop_type = prop.get("type", "")
                if prop_type in ["person", "cohort", "flag"]:
                    valid_properties.append(prop)
                else:
                    logger.warning(
                        f"Skipping property with unsupported type '{prop_type}': {prop.get('key', 'unknown')}"
                    )

            # Only create groups that have actual properties
            if not valid_properties:
                continue

            group: GroupDict = {
                "properties": valid_properties,
                "rollout_percentage": condition.get("rollout_percentage", 100),
            }

            # For boolean flags (no variants), always set variant to null
            # For multivariate flags, use the condition's variant or null
            if has_variants:
                group["variant"] = condition.get("variant")
            else:
                group["variant"] = None

            groups.append(group)

        return groups

    def _convert_external_flag_to_posthog_format(
        self,
        external_flag: dict[str, Any],
        provider: str,
        environment: str = "production",
        field_mappings: dict[str, FieldMappingDict] | None = None,
        team: "Team | None" = None,
    ) -> PostHogFlagFormatDict:
        """Convert external flag to PostHog FeatureFlag model format"""
        key = external_flag.get("key", "")
        name = external_flag.get("name", "") or key

        provider_importer = self._get_provider_importer(provider)
        enabled = provider_importer.extract_enabled_state(external_flag, environment)

        variants = external_flag.get("variants", [])
        filters: FiltersDict = {"groups": [], "payloads": {}, "multivariate": None}
        has_variants = False

        if variants:
            multivariate_filters = provider_importer.build_multivariate_filters(external_flag, variants, environment)
            if multivariate_filters:
                filters["multivariate"] = multivariate_filters.get("multivariate")
                filters["payloads"] = multivariate_filters.get("payloads", {})
                has_variants = True

        conditions = provider_importer.extract_conditions(external_flag, environment, team)
        if conditions:
            filters["groups"] = self._build_groups_from_conditions(conditions, field_mappings, provider, has_variants)

        return {
            "key": key,
            "name": name,
            "filters": filters,
            "active": enabled,
        }

    def _generate_unique_flag_key(self, original_key: str, team: "Team") -> str:
        """Generate a unique flag key by adding a suffix if the key already exists"""
        import time

        from django.db import transaction

        from posthog.models import FeatureFlag

        if not original_key:
            original_key = "imported_flag"

        # Use atomic transaction to prevent race conditions
        with transaction.atomic():
            # Check if the original key is available
            existing_flag = FeatureFlag.objects.filter(team=team, key=original_key, deleted=False).first()
            if not existing_flag:
                return original_key

            # Generate unique key with suffix
            counter = 1
            max_attempts = 100  # Reduced from 1000 for faster fallback

            while counter <= max_attempts:
                candidate_key = f"{original_key}_{counter}"

                if not FeatureFlag.objects.filter(team=team, key=candidate_key, deleted=False).exists():
                    return candidate_key
                counter += 1

            # Fallback with timestamp and random suffix for high collision scenarios
            timestamp = int(time.time())
            random_suffix = random.randint(1000, 9999)
            fallback_key = f"{original_key}_{timestamp}_{random_suffix}"
            return fallback_key

    def _apply_field_mappings_to_properties(
        self,
        properties: list[PropertyDict],
        field_mappings: dict[str, FieldMappingDict],
        provider: str,
    ) -> list[PropertyDict]:
        """Apply field mappings to transform properties for PostHog"""
        if not properties or not field_mappings:
            return properties

        provider_importer = self._get_provider_importer(provider)
        mapped_properties: list[PropertyDict] = []

        for prop in properties:
            external_key = provider_importer.get_external_key_from_property(prop)
            if external_key and external_key in field_mappings:
                mapping = field_mappings[external_key]
                posthog_field = mapping.get("posthog_field")
                posthog_type = mapping.get("posthog_type", "person")
                if posthog_field:
                    mapped_prop: PropertyDict = {
                        "key": posthog_field,
                        "operator": prop.get("operator", "exact"),
                        "value": prop.get("value"),
                        "type": posthog_type,
                    }
                    mapped_properties.append(mapped_prop)
                else:
                    mapped_properties.append(prop)
            else:
                mapped_properties.append(prop)
        return mapped_properties

    def _validate_flag_field_mappings(
        self,
        flag_data: TransformedFlagDict,
        field_mappings: dict[str, FieldMappingDict] | None,
        provider: str,
    ) -> tuple[bool, str | None]:
        """
        Validate that all required fields in a flag have proper mappings.
        Returns a tuple of (is_valid, error_message).
        """
        if not flag_data or not flag_data.get("conditions"):
            # Flag has no conditions, so no field validation needed
            return True, None

        provider_importer = self._get_provider_importer(provider)
        unmapped_fields = []

        for _condition_idx, condition in enumerate(flag_data.get("conditions", [])):
            properties = condition.get("properties", [])

            for _prop_idx, prop in enumerate(properties):
                external_key = provider_importer.get_external_key_from_property(prop)
                if external_key:
                    if not field_mappings or external_key not in field_mappings:
                        unmapped_fields.append(external_key)
                    else:
                        mapping = field_mappings[external_key]
                        posthog_field = mapping.get("posthog_field")
                        if not posthog_field or not posthog_field.strip():
                            unmapped_fields.append(external_key)

        if unmapped_fields:
            # Remove duplicates and format error message
            unique_unmapped = list(set(unmapped_fields))
            error_msg = f"Flag contains unmapped fields: {', '.join(unique_unmapped)}. All fields used in flag conditions must be mapped to PostHog properties."
            return False, error_msg

        return True, None


class StatsigImporter(BaseImporter):
    def fetch_flags(self, api_key: str, project_key: str | None = None) -> list[dict[str, Any]] | ErrorResult:
        import requests

        headers = {"STATSIG-API-KEY": api_key, "STATSIG-API-VERSION": "20240601", "Content-Type": "application/json"}

        all_flags: list[dict[str, Any]] = []

        try:
            gates_endpoint = "https://statsigapi.net/console/v1/gates"
            gates_response = requests.get(gates_endpoint, headers=headers, timeout=30)

            if gates_response.status_code == 401:
                return {"error": "Invalid API key. Please check your Statsig Console API Key.", "status": 401}
            elif gates_response.status_code == 403:
                return {
                    "error": "Access denied. Please ensure your API key has the required permissions.",
                    "status": 403,
                }
            elif gates_response.status_code == 200:
                gates_data = gates_response.json()
                if isinstance(gates_data, dict):
                    gates_list = gates_data.get("data", [])
                    for gate in gates_list:
                        gate["_statsig_type"] = "feature_gate"
                    all_flags.extend(gates_list)
                else:
                    logger.warning(f"Unexpected gates response format: {type(gates_data)}")
            else:
                logger.warning(f"Failed to fetch gates: {gates_response.status_code}")

            configs_endpoint = "https://statsigapi.net/console/v1/dynamic_configs"
            configs_response = requests.get(configs_endpoint, headers=headers, timeout=30)

            if configs_response.status_code == 200:
                configs_data = configs_response.json()
                if isinstance(configs_data, dict):
                    configs_list = configs_data.get("data", [])
                    for config in configs_list:
                        config["_statsig_type"] = "dynamic_config"
                    all_flags.extend(configs_list)
                else:
                    logger.warning(f"Unexpected configs response format: {type(configs_data)}")
            else:
                logger.warning(f"Failed to fetch configs: {configs_response.status_code}")

            return all_flags

        except requests.RequestException as e:
            logger.exception(f"Request failed: {str(e)}")
            return {"error": f"Failed to connect to Statsig API: {str(e)}", "status": 400}
        except Exception as e:
            logger.exception(f"Unexpected error: {str(e)}")
            return {"error": f"Unexpected error fetching Statsig flags: {str(e)}", "status": 500}

    def extract_fields_from_external_flag(self, flag: dict[str, Any]) -> list[FieldInfoDict]:
        field_info_list = []
        metadata = flag.get("metadata", {})

        if "original_rules" in metadata:
            original_rules = metadata["original_rules"]

            for _rule_idx, rule in enumerate(original_rules):
                rule_conditions = rule.get("conditions", [])

                for _cond_idx, condition in enumerate(rule_conditions):
                    # Skip "public" type conditions as they don't require field mapping
                    condition_type = condition.get("type", "")
                    if condition_type == "public":
                        continue

                    condition_key = self._get_condition_key(condition)
                    field_info = self._create_field_info(condition_key)
                    if field_info:
                        field_info_list.append(field_info)

        unique_fields = {}
        for field_info in field_info_list:
            key = (field_info["type"], field_info["key"])
            if key not in unique_fields:
                unique_fields[key] = field_info

        return list(unique_fields.values())

    def _create_field_info(self, attribute: str) -> FieldInfoDict | None:
        if not attribute:
            return None

        display_name = attribute.replace("_", " ").title()
        return {
            "external_key": attribute,
            "key": attribute,
            "type": "field",
            "description": f"Field: {attribute}",
            "display_name": display_name,
        }

    def extract_field_info(self, prop: PropertyDict) -> FieldInfoDict | None:
        prop_key = prop.get("key", "")
        prop_type = prop.get("type", "")

        if prop_type == "cohort":
            return None

        if prop_key:
            return {"type": "field", "key": prop_key, "display_name": f"Field: {prop_key}"}

        if prop_type and prop_type not in ["person", "event", "cohort"]:
            return {
                "type": "field",
                "key": prop_type,
                "display_name": f"Field: {prop_type.replace('_', ' ').title()}",
            }

        return None

    def transform_flag_for_response(
        self,
        raw_flag: dict[str, Any],
        environment: str = "production",
        api_key: str | None = None,
        project_key: str | None = None,
    ) -> TransformedFlagDict:
        """Transform Statsig gate to PostHog response format"""
        gate_id = raw_flag.get("id", "unknown")
        gate_name = raw_flag.get("name", "")

        is_importable, import_issues = self.check_flag_importable(raw_flag)

        return {
            "key": gate_id,
            "name": gate_name or gate_id,
            "description": raw_flag.get("description", ""),
            "enabled": raw_flag.get("isEnabled", False),
            "conditions": self._extract_conditions(raw_flag),
            "variants": self._transform_variants(raw_flag),
            "metadata": {
                "provider": PROVIDER_STATSIG,
                "statsig_type": raw_flag.get("_statsig_type", "feature_gate"),
                "original_id": gate_id,
                "created_at": raw_flag.get("createdTime"),
                "updated_at": raw_flag.get("lastModifierTime"),
                "creator": raw_flag.get("creatorID"),
                "last_modifier": raw_flag.get("lastModifierID"),
                "original_rules": raw_flag.get("rules", []),
            },
            "importable": is_importable,
            "import_issues": import_issues,
        }

    def _is_condition_type_supported(self, condition_type: str) -> bool:
        """Check if a Statsig condition type is supported for import."""
        supported_types = [
            "public",
            "pass_gate",
            "fail_gate",
            "user_id",
            "email",
            "country",
            "region",
            "ip",
            "custom_field",
            "browser_name",
            "browser_version",
            "os_name",
            "os_version",
            "app_version",
        ]
        return condition_type in supported_types

    def check_flag_importable(self, flag: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Check if a Statsig flag/gate/config can be imported to PostHog.

        Returns:
            Tuple of (is_importable, list_of_issues)
        """
        statsig_type = flag.get("_statsig_type", "")

        if statsig_type == "dynamic_config":
            return self._check_dynamic_config_importable(flag)
        else:
            return self._check_gate_importable(flag)

    def _check_gate_importable(self, gate: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Check if a Statsig feature gate can be imported.

        Returns:
            Tuple of (is_importable, list_of_issues)
        """
        issues: list[str] = []

        try:
            if not gate.get("isEnabled", False):
                issues.append("Gate is disabled")

            rules = gate.get("rules", [])

            for rule in rules:
                conditions = rule.get("conditions", [])

                for condition in conditions:
                    condition_type = condition.get("type", "")
                    if not self._is_condition_type_supported(condition_type):
                        issues.append(f"Unsupported condition type: {condition_type}")
                        break

            return len(issues) == 0, issues
        except (KeyError, TypeError):
            return False, ["Invalid gate structure"]

    def _check_dynamic_config_importable(self, config: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Check if a Statsig dynamic config can be imported.

        Returns:
            Tuple of (is_importable, list_of_issues)
        """
        issues: list[str] = []

        try:
            if not config.get("isEnabled", False):
                issues.append("Config is disabled")

            # Check for variant consistency across rules
            variant_consistency_issue = self._validate_dynamic_config_variants(config)
            if variant_consistency_issue:
                issues.append(variant_consistency_issue)

            rules = config.get("rules", [])

            for rule in rules:
                conditions = rule.get("conditions", [])

                for condition in conditions:
                    condition_type = condition.get("type", "")
                    if not self._is_condition_type_supported(condition_type):
                        issues.append(f"Unsupported condition type: {condition_type}")
                        break

            return len(issues) == 0, issues
        except (KeyError, TypeError):
            return False, ["Invalid config structure"]

    def _extract_conditions(self, gate: dict[str, Any]) -> list[ConditionDict]:
        conditions: list[ConditionDict] = []
        rules = gate.get("rules", [])
        is_dynamic_config = gate.get("_statsig_type") == "dynamic_config"

        for rule in rules:
            pass_percentage = rule.get("passPercentage", 100)
            rule_name = rule.get("name", "").lower()
            rule_conditions = rule.get("conditions", [])

            if "default" in rule_name and ("fail" in rule_name or "false" in rule_name):
                continue

            if not rule_conditions:
                continue

            all_properties: list[PropertyDict] = []
            for condition in rule_conditions:
                properties = self._transform_condition(condition)
                all_properties.extend(properties)

            if all_properties:
                if is_dynamic_config:
                    rule_variants = rule.get("variants", [])
                    if rule_variants:
                        total_variant_percentage = sum(v.get("passPercentage", 0) for v in rule_variants)
                        rollout_percentage = total_variant_percentage
                    else:
                        rollout_percentage = pass_percentage
                else:
                    rollout_percentage = pass_percentage

                condition_data: ConditionDict = {
                    "properties": all_properties,
                    "rollout_percentage": rollout_percentage,
                    "rule_id": rule.get("id"),
                }
                conditions.append(condition_data)

        return conditions

    def _get_condition_field_name(self, condition: dict[str, Any]) -> str:
        """Extract the field name from a Statsig condition (without custom_field_ prefix)."""
        condition_type = condition.get("type", "")
        if condition_type == "custom_field":
            return condition.get("field", "")
        return condition_type

    def _get_condition_key(self, condition: dict[str, Any]) -> str:
        """Extract the property key from a Statsig condition (with custom_field_ prefix for custom fields)."""
        condition_type = condition.get("type", "")
        if condition_type == "custom_field":
            field_name = condition.get("field", "")
            return f"custom_field_{field_name}" if field_name else ""
        return condition_type

    def _transform_condition(self, condition: dict[str, Any]) -> list[PropertyDict]:
        """
        Transform Statsig condition to PostHog property format.

        Input (Statsig format):
            {"type": "email", "targetValue": ["user@example.com"]}
            {"type": "user_id", "targetValue": ["user-123", "user-456"]}
            {"type": "custom_field", "field": "plan_type", "targetValue": ["premium"]}
            {"type": "public"}  # No targeting, applies to everyone

        Output (PostHog format):
            [{"key": "email", "operator": "exact", "value": "user@example.com", "type": "person"}]
            [{"key": "user_id", "operator": "in", "value": ["user-123", "user-456"], "type": "person"}]
            [{"key": "custom_field_plan_type", "operator": "exact", "value": "premium", "type": "person"}]
            []  # For "public" type - no properties needed
        """
        properties: list[PropertyDict] = []
        condition_type = condition.get("type", "")

        # "public" type conditions apply to everyone and don't need any properties
        if condition_type == "public":
            return []

        key = self._get_condition_key(condition)
        target_value = condition.get("targetValue", [])

        if key and target_value:
            prop: PropertyDict = {
                "key": key,
                "operator": "exact" if len(target_value) == 1 else "in",
                "value": target_value[0] if len(target_value) == 1 else target_value,
                "type": "person",
            }
            properties.append(prop)

        return properties

    def _transform_variants(self, gate: dict[str, Any]) -> list[VariantDict]:
        variants: list[VariantDict] = []

        if gate.get("_statsig_type") == "dynamic_config":
            return self._extract_dynamic_config_variants(gate)

        return_value = gate.get("defaultValue", True)

        if isinstance(return_value, bool):
            variants = [
                {
                    "key": "true",
                    "name": "Enabled",
                    "value": True,
                    "rollout_percentage": 100 if gate.get("isEnabled") else 0,
                },
                {
                    "key": "false",
                    "name": "Disabled",
                    "value": False,
                    "rollout_percentage": 0 if gate.get("isEnabled") else 0,
                },
            ]
        else:
            variants = [
                {
                    "key": "enabled",
                    "name": "Enabled",
                    "value": return_value,
                    "rollout_percentage": 100 if gate.get("isEnabled") else 0,
                }
            ]

        return variants

    def _extract_dynamic_config_variants(self, config: dict[str, Any]) -> list[VariantDict]:
        variants: list[VariantDict] = []
        rules = config.get("rules", [])
        variant_sets_by_rule: list[list[VariantDict]] = []

        for _rule_idx, rule in enumerate(rules):
            rule_variants = rule.get("variants", [])

            if rule_variants:
                rule_variant_set: list[VariantDict] = []
                for variant in rule_variants:
                    variant_value = variant.get("returnValue")

                    if not variant_value and variant.get("returnValueJson5"):
                        json5_str = variant.get("returnValueJson5", "{}")

                        try:
                            import json

                            cleaned_json = "\n".join(
                                line for line in json5_str.split("\n") if not line.strip().startswith("//")
                            )

                            if cleaned_json.strip() and cleaned_json.strip() != "{}":
                                variant_value = json.loads(cleaned_json)
                            else:
                                variant_value = {}
                        except Exception as e:
                            logger.warning(f"Statsig: Failed to parse JSON5 for variant {variant.get('name')}: {e}")
                            variant_value = {}

                    if variant_value is None:
                        variant_value = variant.get("returnValue", {})

                    variant_data: VariantDict = {
                        "key": variant.get("name", variant.get("id", "")),
                        "name": variant.get("name", variant.get("id", "")),
                        "value": variant_value,
                        "rollout_percentage": variant.get("passPercentage", 0),
                    }
                    rule_variant_set.append(variant_data)
                variant_sets_by_rule.append(rule_variant_set)

        if variant_sets_by_rule:
            baseline_variants = variant_sets_by_rule[0]

            for i, rule_variants in enumerate(variant_sets_by_rule[1:], 1):
                if not self._variants_are_consistent(baseline_variants, rule_variants):
                    logger.warning(
                        f"Statsig Dynamic Config: Inconsistent variants found between rules. Rule 0 vs Rule {i}"
                    )
                    return []

            variants = baseline_variants
        else:
            default_value = config.get("defaultValue")
            if default_value is not None:
                variants = [
                    {
                        "key": "default",
                        "name": "Default Value",
                        "value": default_value,
                        "rollout_percentage": 100 if config.get("isEnabled") else 0,
                    }
                ]

        return variants

    def _validate_dynamic_config_variants(self, config: dict[str, Any]) -> str | None:
        rules = config.get("rules", [])

        if len(rules) <= 1:
            return None

        variant_sets_by_rule: list[tuple[int, list[VariantDict]]] = []

        for rule_idx, rule in enumerate(rules):
            rule_variants = rule.get("variants", [])
            if rule_variants:
                rule_variant_set: list[VariantDict] = []
                for variant in rule_variants:
                    variant_data: VariantDict = {
                        "key": variant.get("name", variant.get("id", "")),
                        "name": variant.get("name", variant.get("id", "")),
                        "rollout_percentage": variant.get("passPercentage", 0),
                    }
                    rule_variant_set.append(variant_data)
                variant_sets_by_rule.append((rule_idx, rule_variant_set))

        if len(variant_sets_by_rule) <= 1:
            return None

        baseline_rule_idx, baseline_variants = variant_sets_by_rule[0]

        for rule_idx, rule_variants in variant_sets_by_rule[1:]:
            if not self._variants_are_consistent(baseline_variants, rule_variants):
                return f"Inconsistent variants/splits between rules. Rule {baseline_rule_idx} vs Rule {rule_idx} have different variant configurations"

        return None

    def _variants_are_consistent(self, variants1: list[VariantDict], variants2: list[VariantDict]) -> bool:
        if len(variants1) != len(variants2):
            return False

        sorted1 = sorted(variants1, key=lambda v: v.get("key", ""))
        sorted2 = sorted(variants2, key=lambda v: v.get("key", ""))

        for v1, v2 in zip(sorted1, sorted2):
            v1_percentage = v1.get("rollout_percentage", v1.get("percentage", 0))
            v2_percentage = v2.get("rollout_percentage", v2.get("percentage", 0))

            if v1.get("key") != v2.get("key") or v1_percentage != v2_percentage:
                return False

        return True

    def extract_enabled_state(self, external_flag: dict[str, Any], environment: str) -> bool:
        return external_flag.get("enabled", True)

    def build_multivariate_filters(
        self, external_flag: dict[str, Any], variants: list[VariantDict], environment: str
    ) -> MultivariateFiltersResult | None:
        import json

        posthog_variants: list[PostHogVariantDict] = []
        posthog_payloads: dict[str, Any] = {}

        for variant in variants:
            variant_value = variant.get("value")
            variant_key = variant.get("key", "")

            if variant_value not in [True, False, "true", "false"]:
                posthog_variants.append(
                    {
                        "key": variant_key,
                        "name": variant.get("name", ""),
                        "rollout_percentage": variant.get("rollout_percentage", 0),
                    }
                )
                if variant_value is not None:
                    posthog_payloads[variant_key] = variant_value

        if posthog_variants:
            top_level_payloads: dict[str, str | None] = {}
            for variant_key, payload_value in posthog_payloads.items():
                top_level_payloads[variant_key] = json.dumps(payload_value) if payload_value is not None else None

            return {
                "payloads": top_level_payloads,
                "multivariate": {
                    "variants": posthog_variants,
                    "payloads": posthog_payloads,
                },
            }
        return None

    def extract_conditions(
        self, external_flag: dict[str, Any], environment: str, team: "Team | None"
    ) -> list[ConditionDict]:
        return external_flag.get("conditions", [])

    def get_external_key_from_property(self, prop: PropertyDict) -> str | None:
        return prop.get("key")


class LaunchDarklyImporter(BaseImporter):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rate_limiter = LaunchDarklyRateLimiter()

    def fetch_flags(self, api_key: str, project_key: str | None = None) -> list[dict[str, Any]] | ErrorResult:
        """Fetch flags from LaunchDarkly API"""
        headers = {"Authorization": api_key, "LD-API-Version": "20240415", "Content-Type": "application/json"}

        list_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}"

        response, success = self.rate_limiter.make_request_with_rate_limiting(list_endpoint, headers)

        if not success:
            if response.status_code == 429:
                return {"error": "LaunchDarkly API rate limit exceeded. Please try again later.", "status": 429}
            else:
                return {
                    "error": f"Failed to fetch flags list: {response.status_code} {response.reason}",
                    "status": 400,
                }

        launchdarkly_response = response.json()

        if isinstance(launchdarkly_response, dict):
            flags_list = launchdarkly_response.get("items", [])
        else:
            flags_list = launchdarkly_response if isinstance(launchdarkly_response, list) else []

        external_flags: list[dict[str, Any]] = []
        for flag_summary in flags_list:
            try:
                flag_key = flag_summary.get("key")
                detail_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}/{flag_key}"
                detail_response, detail_success = self.rate_limiter.make_request_with_rate_limiting(
                    detail_endpoint, headers, max_retries=3
                )

                if detail_success:
                    if detail_response.status_code == 200:
                        flag_detail = detail_response.json()
                        external_flags.append(flag_detail)
                    elif detail_response.status_code == 429:
                        rate_limited_flag = dict(flag_summary)
                        rate_limited_flag["_rate_limited"] = True
                        rate_limited_flag["_rate_limit_reason"] = "Max retries exceeded due to rate limiting"
                        external_flags.append(rate_limited_flag)
                        logger.warning(f"Flag {flag_key} rate limited after retries, using summary data")
                    else:
                        logger.warning(
                            f"Failed to fetch details for flag {flag_key}: {detail_response.status_code}, using summary data"
                        )
                        external_flags.append(flag_summary)
                else:
                    logger.warning(f"Request failed for flag {flag_key}, using summary data")
                    external_flags.append(flag_summary)
            except Exception as e:
                logger.exception(
                    f"Exception processing flag {flag_key if 'flag_key' in locals() else 'unknown'}: {str(e)}"
                )
                continue

        return external_flags

    def transform_flag_for_response(
        self,
        raw_flag: dict[str, Any],
        environment: str = "production",
        api_key: str | None = None,
        project_key: str | None = None,
    ) -> TransformedFlagDict:
        is_importable, import_issues = self.check_flag_importable(raw_flag, environment)

        conditions = self.transform_conditions(raw_flag, environment)

        environments = raw_flag.get("environments", {})
        selected_env = environments.get(environment, {})
        environment_enabled = selected_env.get("on", False)

        return {
            "key": raw_flag.get("key", ""),
            "name": raw_flag.get("name") or raw_flag.get("key", ""),
            "description": raw_flag.get("description", ""),
            "enabled": environment_enabled,
            "conditions": conditions,
            "variants": self._transform_variants(raw_flag),
            "metadata": {
                "provider": PROVIDER_LAUNCHDARKLY,
                "original_id": str(raw_flag.get("_id", raw_flag.get("key", ""))),
                "created_at": raw_flag.get("creationDate"),
                "updated_at": raw_flag.get("_lastModified"),
                "environments": {environment: True},  # Store as dict with environment as key
                "tags": raw_flag.get("tags", []),
                "total_rules": len(conditions),
                "has_prerequisites": bool(raw_flag.get("prerequisites")),
                "environment_configs": self._extract_environment_data(raw_flag, environment),
                "raw_environments": raw_flag.get("environments", {}),
                "raw_variations": raw_flag.get("variations", []),
                "raw_key": raw_flag.get("key", ""),
                "debug_raw_flag_keys": list(raw_flag.keys()),
                "api_key": api_key,
                "project_key": project_key,
            },
            "importable": is_importable and len(import_issues) == 0,
            "import_issues": import_issues,
        }

    def transform_conditions(
        self,
        flag: dict[str, Any],
        environment: str = "production",
        api_key: str | None = None,
        project_key: str | None = None,
        team: "Team | None" = None,
    ) -> list[ConditionDict]:
        """Transform LaunchDarkly targeting rules to PostHog condition format"""
        conditions: list[ConditionDict] = []

        if not isinstance(flag, dict):
            return [{"properties": [], "rollout_percentage": 0}]

        # Get specified environment from raw_environments (preferred) or transformed environments
        raw_environments = flag.get("metadata", {}).get("raw_environments", {})
        target_env = raw_environments.get(environment)

        if not target_env:
            # Fallback to transformed environments
            environments = flag.get("environments", {})
            if environment in environments:
                target_env = environments[environment]
            else:
                # Fallback to first enabled environment
                for env_data in environments.values():
                    if env_data.get("on", False):
                        target_env = env_data
                        break

        if not target_env or not target_env.get("on", False):
            return [{"properties": [], "rollout_percentage": 0}]

        # Extract targeting from specified environment
        targeting = target_env

        # Process individual target users first (if any)
        if targeting.get("targets"):
            for target in targeting["targets"]:
                if target.get("values"):  # Has specific users
                    condition: ConditionDict = {
                        "properties": [
                            {"key": "distinct_id", "operator": "exact", "value": target["values"], "type": "person"}
                        ],
                        "rollout_percentage": 100,
                        "variant": self._get_variation_key(flag, target.get("variation")),
                    }
                    conditions.append(condition)

        # Process context targets (user segments)
        if targeting.get("contextTargets"):
            for context_target in targeting["contextTargets"]:
                if context_target.get("values"):
                    context_condition: ConditionDict = {
                        "properties": [
                            {
                                "key": context_target.get("contextKind", "user"),
                                "operator": "exact",
                                "value": context_target["values"],
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": self._get_variation_key(flag, context_target.get("variation")),
                    }
                    conditions.append(context_condition)

        # Process custom targeting rules (this now supports attributes mapping)
        for rule_idx, rule in enumerate(targeting.get("rules", [])):
            condition: ConditionDict = {
                "properties": [],
                "rollout_percentage": 100,
                "rule_id": rule.get("_id", f"rule_{rule_idx}"),
            }

            # Transform clauses to properties (maps LaunchDarkly attributes to PostHog)
            for clause in rule.get("clauses", []):
                prop = self._transform_clause(clause, api_key, project_key, environment, team)
                if prop:
                    condition["properties"].append(prop)

            # Handle rollout/variation distribution
            if rule.get("rollout"):
                # For multivariate rules with rollout, the release condition should be 100%
                # The variant distribution is handled separately in the multivariate configuration
                condition["rollout_percentage"] = 100
            elif rule.get("variation") is not None:
                # Direct variation assignment - rule serves a specific variant to 100% of matching users
                condition["rollout_percentage"] = 100
                condition["variant"] = self._get_variation_key(flag, rule.get("variation"))

            # Only add conditions that have properties (custom targeting) or specific variants
            # Also filter out conditions with 0% rollout as they serve no purpose
            if (condition["properties"] or condition.get("variant")) and condition.get("rollout_percentage", 0) > 0:
                conditions.append(condition)

        # Always add fallthrough rule if it exists - it handles users who don't match custom rules
        if targeting.get("fallthrough"):
            fallthrough = targeting["fallthrough"]

            # Determine rollout percentage based on fallthrough type
            rollout_percentage = 100  # Default
            fallthrough_variant = None

            # Handle percentage rollout in fallthrough
            if fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
                rollout = fallthrough["rollout"]
                variations = rollout["variations"]
                total_weight = sum(v.get("weight", 0) for v in variations)
                off_variation = targeting.get("offVariation", 1)

                # Calculate the percentage for the "on" variation (not the off variation)
                on_rollout_percentage = 0
                for variation_config in variations:
                    variation_index = variation_config.get("variation")
                    weight = variation_config.get("weight", 0)

                    if variation_index != off_variation and total_weight > 0:
                        # This is an "on" variation, add its percentage
                        on_rollout_percentage += int((weight / total_weight) * 100)

                        # For boolean flags, set the variant if it's the primary "on" variation
                        if flag.get("kind") == "boolean" and variation_index is not None:
                            fallthrough_variant = self._get_variation_key(flag, variation_index)
                    elif variation_index == off_variation and total_weight > 0:
                        # For multivariate flags, we might still want to track the off variation
                        if flag.get("kind") != "boolean" and variation_index is not None:
                            fallthrough_variant = self._get_variation_key(flag, variation_index)

                rollout_percentage = on_rollout_percentage

            elif fallthrough.get("variation") is not None:
                # Handle direct variation assignment
                variation_index = fallthrough.get("variation")
                off_variation = targeting.get("offVariation", 1)

                if variation_index == off_variation:
                    rollout_percentage = 0  # Flag is off for fallthrough users
                else:
                    rollout_percentage = 100  # Flag is on for fallthrough users

                fallthrough_variant = self._get_variation_key(flag, variation_index)

            fallthrough_condition: ConditionDict = {
                "properties": [],
                "rollout_percentage": rollout_percentage,
                "rule_id": "fallthrough",
            }

            # Add variant if determined
            if fallthrough_variant:
                fallthrough_condition["variant"] = fallthrough_variant

            # Only add fallthrough condition if it has rollout > 0%
            if rollout_percentage > 0:
                conditions.append(fallthrough_condition)

        # Handle case where no conditions remain (all were 0% rollout)
        if not conditions:
            # When all conditions are filtered out due to 0% rollout,
            # the flag is effectively disabled for all users
            # Return empty conditions list to represent this state
            final_conditions = []
        else:
            final_conditions = conditions

        return final_conditions

    def check_flag_importable(self, flag: dict[str, Any], environment: str = "production") -> tuple[bool, list[str]]:
        """
        Check if a LaunchDarkly flag can be imported to PostHog.

        Returns:
            Tuple of (is_importable, list_of_issues)
        """
        issues: list[str] = []
        flag_key = flag.get("key", "unknown")

        if not isinstance(flag, dict):
            return False, ["Invalid flag structure"]

        # Check for rate limiting
        if flag.get("_rate_limited"):
            issues.append("API rate limit exceeded - try again in a few minutes")
            return False, issues

        # Check for prerequisites
        if flag.get("prerequisites") and len(flag["prerequisites"]) > 0:
            issues.append("Flag prerequisites not supported")
            return False, issues

        # Check for progressive rollout
        if self._has_progressive_rollout(flag, environment):
            issues.append("Progressive rollout flags not supported")
            return False, issues

        # Check for migration flags
        if self._is_migration_flag(flag):
            issues.append("Migration flags not supported (infrastructure/system migration flags)")
            return False, issues

        # Check environments
        environments = flag.get("environments", {})
        if not environments:
            issues.append("No environments found")
            return False, issues

        env_data = environments.get(environment)
        if not env_data:
            logger.warning(
                f"Flag {flag_key}: rejected - environment '{environment}' not found. Available: {list(environments.keys())}"
            )
            issues.append(f"Environment '{environment}' not found")
            return False, issues

        # Check if flag is enabled in the environment
        if not env_data.get("on", False):
            issues.append(f"Flag is disabled in '{environment}' environment")
            return False, issues

        # Check for individual user targeting
        if env_data.get("targets") or env_data.get("contextTargets"):
            issues.append("Individual user targeting not supported")
            return False, issues

        # Check for fallthrough rule
        if not env_data.get("fallthrough"):
            issues.append("No fallthrough rule found")
            return False, issues

        # Check for multiple percentage rollouts
        rules = env_data.get("rules", [])
        fallthrough = env_data.get("fallthrough", {})

        percentage_rollout_count = 0
        for rule in rules:
            if rule.get("rollout") and rule["rollout"].get("variations"):
                percentage_rollout_count += 1

        if fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
            percentage_rollout_count += 1

        if percentage_rollout_count > 1:
            issues.append(f"Multiple percentage rollout rules not supported ({percentage_rollout_count} found)")
            return False, issues

        # Check for segment matching
        for rule in rules:
            for clause in rule.get("clauses", []):
                if clause.get("op") == "segmentMatch":
                    issues.append("Segment matching not supported")
                    return False, issues

        # Check for invalid variant keys
        variations = flag.get("variations", [])
        invalid_variants = []
        for variation in variations:
            if "value" in variation and variation["value"] not in [True, False]:
                variant_key = variation.get("name", "")
                if not self._is_valid_variant_key(variant_key):
                    invalid_variants.append(variant_key)

        if invalid_variants:
            issues.append(
                f"Invalid variant keys (only letters, numbers, hyphens, underscores allowed): {', '.join(invalid_variants)}"
            )
            return False, issues

        return True, []

    def _get_variation_key(self, flag: dict[str, Any], variation_index: int | None) -> str | None:
        """Get the variation key from the flag's variations list"""
        if variation_index is None:
            return None

        variations = flag.get("variations", [])
        if isinstance(variation_index, int) and 0 <= variation_index < len(variations):
            variation = variations[variation_index]
            return variation.get("value", str(variation_index))

        return str(variation_index)

    def extract_fields_from_external_flag(self, flag: dict[str, Any]) -> list[FieldInfoDict]:
        field_info_list: list[FieldInfoDict] = []

        # Look at the detailed environment configs for rule criteria
        metadata = flag.get("metadata", {})
        environment_configs = metadata.get("environment_configs", {})

        for _env_name, env_config in environment_configs.items():
            detailed_rules = env_config.get("detailed_rules", [])

            for rule in detailed_rules:
                clauses = rule.get("clauses", [])

                for clause in clauses:
                    attribute = clause.get("attribute", "")
                    if attribute and attribute not in ["key", "user"]:
                        field_info = self._create_field_info(attribute)
                        if field_info:
                            field_info_list.append(field_info)

        return field_info_list

    def _create_field_info(self, attribute: str) -> FieldInfoDict | None:
        """Create field info for a LaunchDarkly attribute/criteria field"""
        if not attribute:
            return None

        # Determine if this is a built-in PostHog property or a custom field
        if attribute.startswith("$") or attribute in ["email", "country", "region", "city"]:
            field_type = "built_in"
            description = attribute
            display_name = attribute.replace("_", " ").title()
        else:
            field_type = "custom"
            description = f"Custom Field: {attribute}"
            display_name = attribute.replace("_", " ").title()

        return {
            "external_key": attribute,
            "key": attribute,
            "type": field_type,
            "description": description,
            "display_name": display_name,
        }

    def extract_production_config(self, raw_flag: dict[str, Any], environment: str = "production") -> tuple[bool, int]:
        """Extract enabled state and rollout percentage from LaunchDarkly specified environment"""
        environments = raw_flag.get("environments", {})

        # Try specified environment first, then fall back to any enabled environment
        target_env = None
        if environment in environments:
            target_env = environments[environment]
        else:
            # Fallback to first enabled environment
            for _env_name, env_data in environments.items():
                if env_data.get("on", False):
                    target_env = env_data
                    break

        if not target_env:
            return False, 0  # No enabled environments

        enabled = target_env.get("on", False)

        # Extract rollout percentage from fallthrough
        fallthrough = target_env.get("fallthrough", {})
        rollout_percentage = 100  # Default to 100%

        if fallthrough.get("rollout"):
            # Has rollout configuration
            rollout = fallthrough["rollout"]
            variations = rollout.get("variations", [])

            # Calculate percentage for "true" variation (usually variation 0 or 1)
            total_weight = sum(v.get("weight", 0) for v in variations)
            if total_weight > 0:
                # Find the "true" variation - usually the one that's not the "off" variation
                off_variation = target_env.get("offVariation", 0)
                for variation in variations:
                    variation_index = variation.get("variation")
                    if variation_index != off_variation:
                        weight = variation.get("weight", 0)
                        rollout_percentage = int((weight / total_weight) * 100)
                        break
        elif fallthrough.get("variation") is not None:
            # Direct variation assignment
            variation_index = fallthrough.get("variation")
            off_variation = target_env.get("offVariation", 0)

            if variation_index == off_variation:
                rollout_percentage = 0  # Flag is off
            else:
                rollout_percentage = 100  # Flag is fully on

        return enabled, rollout_percentage

    def extract_variant_rollouts(
        self, raw_flag: dict[str, Any], transformed_variants: list[VariantDict], environment: str = "production"
    ) -> dict[str, int]:
        """Extract variant rollout percentages from LaunchDarkly specified environment"""
        environments = raw_flag.get("environments", {})

        # Get specified environment or fallback to first enabled environment
        target_env = None
        if environment in environments:
            target_env = environments[environment]
        else:
            for _env_name, env_data in environments.items():
                if env_data.get("on", False):
                    target_env = env_data
                    break

        if not target_env:
            return {}

        # Extract variant rollouts from rules or fallthrough configuration
        rules = target_env.get("rules", [])
        fallthrough = target_env.get("fallthrough", {})
        variant_rollouts = {}

        # First, check rules for rollout with variations
        rollout_found = False
        for _rule_idx, rule in enumerate(rules):
            if rule.get("rollout") and rule["rollout"].get("variations"):
                rollout = rule["rollout"]
                variations = rollout["variations"]
                total_weight = sum(v.get("weight", 0) for v in variations)

                if total_weight > 0:
                    # Map rollout variations to transformed variants by variation index
                    for variation_config in variations:
                        variation_index = variation_config.get("variation")
                        weight = variation_config.get("weight", 0)
                        percentage = int((weight / total_weight) * 100)

                        # Map variation index to corresponding transformed variant
                        if variation_index is not None and variation_index < len(transformed_variants):
                            variant = transformed_variants[variation_index]
                            variant_key = variant.get("key", f"variant_{variation_index}")
                            variant_value = variant.get("value")

                            # Skip boolean variants (true/false)
                            if variant_value not in [True, False, "true", "false"]:
                                variant_rollouts[variant_key] = percentage

                    rollout_found = True
                    break

        # If no rollout found in rules, check fallthrough
        if not rollout_found and fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
            rollout = fallthrough["rollout"]
            variations = rollout["variations"]
            total_weight = sum(v.get("weight", 0) for v in variations)

            if total_weight > 0:
                # Map rollout variations to transformed variants by variation index
                for variation_config in variations:
                    variation_index = variation_config.get("variation")
                    weight = variation_config.get("weight", 0)
                    percentage = int((weight / total_weight) * 100)

                    # Map variation index to corresponding transformed variant
                    if variation_index is not None and variation_index < len(transformed_variants):
                        variant = transformed_variants[variation_index]
                        variant_key = variant.get("key", f"variant_{variation_index}")
                        variant_value = variant.get("value")

                        # Skip boolean variants (true/false)
                        if variant_value not in [True, False, "true", "false"]:
                            variant_rollouts[variant_key] = percentage

        return variant_rollouts

    def _has_progressive_rollout(self, flag: dict[str, Any], environment: str = "production") -> bool:
        """Check if a flag uses progressive rollout patterns"""
        if not isinstance(flag, dict):
            return False

        flag_key = flag.get("key", "unknown")
        environments = flag.get("environments", {})
        env_data = environments.get(environment, {})

        if not env_data:
            return False

        # Primary Pattern: Check for experimentAllocation.type = "progressiveRollout"
        fallthrough = env_data.get("fallthrough", {})
        if fallthrough.get("rollout"):
            rollout = fallthrough["rollout"]
            experiment_allocation = rollout.get("experimentAllocation", {})

            if experiment_allocation.get("type") == "progressiveRollout":
                return True

        # Pattern 1: Check for progressive rollout in rules (only if experimentAllocation indicates it)
        rules = env_data.get("rules", [])
        for rule in rules:
            if rule.get("rollout") and rule["rollout"].get("variations"):
                rule_experiment_allocation = rule["rollout"].get("experimentAllocation", {})
                if rule_experiment_allocation.get("type") == "progressiveRollout":
                    return True

        # Pattern 2: Check if flag name suggests progressive rollout
        flag_name = flag.get("name", "").lower()
        flag_key_lower = flag_key.lower()
        progressive_keywords = ["progressive", "rollout", "gradual", "staged", "canary", "phased"]

        if any(keyword in flag_name or keyword in flag_key_lower for keyword in progressive_keywords):
            return True

        return False

    def _is_migration_flag(self, flag: dict[str, Any]) -> bool:
        """Check if a flag is a migration flag (used for infrastructure/system migrations)"""
        if not isinstance(flag, dict):
            return False

        flag_key = flag.get("key", "").lower()
        flag_name = flag.get("name", "").lower()
        description = flag.get("description", "").lower()

        # Check explicit purpose field
        purpose = flag.get("_purpose")
        if purpose == "migration":
            return True

        # Check for migration keywords in flag key, name, or description
        migration_keywords = [
            "migration",
            "migrate",
            "dualwrite",
            "shadow",
            "rampdown",
            "fallback",
            "rollback",
            "cutover",
            "switch-over",
            "infrastructure",
        ]

        for keyword in migration_keywords:
            if keyword in flag_key or keyword in flag_name or keyword in description:
                return True

        # Check for classic migration stage patterns in variants
        variations = flag.get("variations", [])
        if len(variations) >= 4:  # Migration flags typically have multiple stages
            variant_values = [str(v.get("value", "")).lower() for v in variations]
            variant_names = [str(v.get("name", "")).lower() for v in variations]

            # Look for classic migration stages
            migration_stages = ["off", "dualwrite", "shadow", "live", "rampdown", "complete"]

            # Check if majority of variants match migration stages
            matching_stages = 0
            for stage in migration_stages:
                if any(stage in value or stage in name for value, name in zip(variant_values, variant_names)):
                    matching_stages += 1

            # If 4+ migration stages are present, likely a migration flag
            if matching_stages >= 4:
                return True

        # Check for temporary flag status (migration flags are often temporary)
        if flag.get("temporary", False):
            # Additional checks for temporary flags to ensure we don't exclude all temp flags
            if any(keyword in flag_key or keyword in flag_name for keyword in ["migration", "migrate", "cutover"]):
                return True

        return False

    def _is_clause_supported(self, clause: dict[str, Any]) -> bool:
        """Check if a LaunchDarkly clause can be converted to PostHog"""
        if not isinstance(clause, dict):
            return False

        attribute = clause.get("attribute", "")
        operator = clause.get("op", "")

        # Supported attributes (map to PostHog properties)
        supported_attributes = {
            "key",  # User ID/distinct_id
            "email",  # Email
            "name",  # Name
            "country",  # Country
            "anonymous",  # Anonymous flag
            "ip",  # IP address
            "userAgent",  # User agent
            "custom",  # Custom attributes (will need specific handling)
        }

        # Supported operators
        supported_operators = {
            "in",  # exact match
            "matches",  # regex
            "startsWith",  # starts with
            "endsWith",  # ends with
            "contains",  # contains
            "lessThan",  # less than
            "lessThanOrEqual",  # less than or equal
            "greaterThan",  # greater than
            "greaterThanOrEqual",  # greater than or equal
        }

        # Check if operator is supported and has values
        attribute_supported = attribute in supported_attributes or bool(attribute)  # Allow any non-empty attribute
        operator_supported = operator in supported_operators
        has_values = clause.get("values") is not None

        return attribute_supported and operator_supported and has_values

    def _transform_clause(
        self,
        clause: dict[str, Any],
        api_key: str | None = None,
        project_key: str | None = None,
        environment: str = "production",
        team: "Team | None" = None,
    ) -> PropertyDict | None:
        """Transform a LaunchDarkly clause to a PostHog property"""
        if not isinstance(clause, dict):
            return None

        attribute = clause.get("attribute", "")
        operator = clause.get("op", "in")
        values = clause.get("values", [])

        # Map LaunchDarkly attributes to PostHog properties
        property_key = self._map_attribute(attribute)

        # Handle different value types
        if not values:
            value = ""
        elif len(values) == 1:
            value = values[0]
        else:
            value = values  # Multiple values

        # Transform value for startsWith/endsWith operators
        if operator == "startsWith" and isinstance(value, str):
            # Escape special regex characters and add ^ anchor for startsWith
            import re

            escaped_value = re.escape(value)
            value = f"^{escaped_value}"
        elif operator == "endsWith" and isinstance(value, str):
            # Escape special regex characters and add $ anchor for endsWith
            import re

            escaped_value = re.escape(value)
            value = f"{escaped_value}$"

        # Map operators
        mapped_operator = self._map_operator(operator)

        return {
            "key": property_key,
            "external_key": attribute,
            "operator": mapped_operator,
            "value": value,
        }

    def _map_attribute(self, attribute: str) -> str:
        """Map LaunchDarkly attributes to PostHog property keys"""
        attribute_map = {
            "email": "email",
            "country": "country",
        }
        return attribute_map.get(attribute, attribute)

    def _transform_variants(self, flag: dict[str, Any]) -> list[VariantDict]:
        """Transform LaunchDarkly variations to PostHog variants format"""
        variations = flag.get("variations", [])
        if not variations:
            return []

        variants: list[VariantDict] = []
        for idx, variation in enumerate(variations):
            # Use variation value as the key (for boolean flags, skip non-boolean variants)
            variation_value = variation.get("value")
            if variation_value in [True, False]:
                # Skip boolean variants as they don't need to be in multivariate
                continue

            # Use variation name as the key (LaunchDarkly variant key)
            variation_name = variation.get("name", f"variant_{idx}")
            variant: VariantDict = {
                "key": variation_name,
                "name": variation_name,
                "rollout_percentage": 0,  # Will be calculated based on targeting rules
                "value": variation_value,
                "description": variation.get("description", ""),
                "is_default": idx == 0,  # First variation is usually the "off" state
            }
            variants.append(variant)

        return variants

    def _map_operator(self, ld_op: str) -> str:
        """Map LaunchDarkly operators to PostHog operators"""
        operator_map = {
            "in": "exact",
            "endsWith": "regex",
            "startsWith": "regex",
            "matches": "regex",
            "contains": "icontains",
            "lessThan": "lt",
            "lessThanOrEqual": "lte",
            "greaterThan": "gt",
            "greaterThanOrEqual": "gte",
            "before": "is_date_before",
            "after": "is_date_after",
            "semVerEqual": "exact",
            "semVerLessThan": "lt",
            "semVerGreaterThan": "gt",
        }
        return operator_map.get(ld_op, "exact")

    def _extract_environment_data(
        self, flag: dict[str, Any], selected_environment: str | None = None
    ) -> dict[str, EnvironmentDataDict]:
        """Extract environment-specific targeting data from LaunchDarkly flag"""
        environments_data: dict[str, EnvironmentDataDict] = {}
        environments = flag.get("environments", {})

        # If selected_environment is specified, only process that environment
        if selected_environment:
            env_items = [(selected_environment, environments.get(selected_environment, {}))]
        else:
            env_items = environments.items()

        for env_name, env_data in env_items:
            # Get basic environment info
            is_on = env_data.get("on", False)
            rules = env_data.get("rules", [])
            targets = env_data.get("targets", [])
            context_targets = env_data.get("contextTargets", [])
            fallthrough = env_data.get("fallthrough", {})

            # Count rules and targets
            rules_count = len(rules)
            has_targets = bool(targets or context_targets)

            # Process rules with detailed information
            detailed_rules: list[RuleInfoDict] = []
            for rule in rules[:3]:  # First 3 rules only for UI performance
                rule_info: RuleInfoDict = {
                    "id": rule.get("_id", ""),
                    "description": rule.get("description", ""),
                    "clauses": [],
                    "rollout_info": None,
                }

                # Process clauses (conditions)
                for clause in rule.get("clauses", []):
                    clause_info: ClauseInfoDict = {
                        "attribute": clause.get("attribute", ""),
                        "operator": clause.get("op", ""),
                        "values": clause.get("values", []),
                        "negate": clause.get("negate", False),
                        "context_kind": clause.get("contextKind", "user"),
                    }
                    rule_info["clauses"].append(clause_info)

                # Handle rollout or direct variation
                if rule.get("rollout"):
                    rollout = rule["rollout"]
                    variations = rollout.get("variations", [])
                    total_weight = sum(v.get("weight", 0) for v in variations)

                    rollout_info: RolloutInfoDict = {"type": "rollout", "variations": []}

                    for variation in variations:
                        weight = variation.get("weight", 0)
                        percentage = int((weight / total_weight) * 100) if total_weight > 0 else 0
                        rollout_info["variations"].append(
                            {"variation": variation.get("variation"), "weight": weight, "percentage": percentage}
                        )

                    rule_info["rollout_info"] = rollout_info
                elif rule.get("variation") is not None:
                    rule_info["rollout_info"] = {"type": "direct", "variation": rule.get("variation")}

                detailed_rules.append(rule_info)

            # Process fallthrough
            fallthrough_info = None
            if fallthrough:
                if fallthrough.get("rollout"):
                    rollout = fallthrough["rollout"]
                    variations = rollout.get("variations", [])
                    total_weight = sum(v.get("weight", 0) for v in variations)

                    fallthrough_info: RolloutInfoDict | DirectVariationInfoDict = {"type": "rollout", "variations": []}

                    for variation in variations:
                        weight = variation.get("weight", 0)
                        percentage = int((weight / total_weight) * 100) if total_weight > 0 else 0
                        fallthrough_info["variations"].append(  # type: ignore[typeddict-item]
                            {"variation": variation.get("variation"), "weight": weight, "percentage": percentage}
                        )
                elif fallthrough.get("variation") is not None:
                    fallthrough_info = {"type": "direct", "variation": fallthrough.get("variation")}

            environments_data[env_name] = {
                "enabled": is_on,
                "rules_count": rules_count,
                "has_targets": has_targets,
                "target_count": len(targets) + len(context_targets),
                "detailed_rules": detailed_rules,
                "fallthrough": fallthrough_info,
                "off_variation": env_data.get("offVariation"),
            }

        return environments_data

    def extract_field_info(self, prop: PropertyDict) -> FieldInfoDict | None:
        """Extract field info from LaunchDarkly property - focusing on actual field keys/criteria"""
        prop_key = prop.get("key", "")
        prop_type = prop.get("type", "person")

        # Skip cohort properties
        if prop_key == "id" and prop_type == "cohort":
            return None

        # Return the actual field key being used as criteria
        if prop_key:
            # Determine if this is a built-in PostHog property or a custom field
            if prop_key.startswith("$") or prop_key in ["email", "country", "region", "city"]:
                field_type = "built_in"
                description = prop_key
            else:
                field_type = "custom"
                description = f"Custom Field: {prop_key}"

            return {"external_key": prop_key, "type": field_type, "description": description}

        return None

    def extract_enabled_state(self, external_flag: dict[str, Any], environment: str) -> bool:
        """Extract the enabled state from LaunchDarkly flag"""
        raw_environments = external_flag.get("metadata", {}).get("raw_environments")
        if raw_environments:
            key = external_flag.get("key", "")
            mock_flag = {"key": key, "environments": raw_environments}
            enabled, _rollout_percentage = self.extract_production_config(mock_flag, environment)
            return enabled
        return external_flag.get("enabled", True)

    def build_multivariate_filters(
        self, external_flag: dict[str, Any], variants: list[VariantDict], environment: str
    ) -> MultivariateFiltersResult | None:
        """Build multivariate filters for LaunchDarkly flags"""
        key = external_flag.get("key", "")
        raw_environments = external_flag.get("metadata", {}).get("raw_environments")
        variant_rollouts: dict[str, int] = {}

        if raw_environments:
            mock_flag = {"key": key, "environments": raw_environments}
            variant_rollouts = self.extract_variant_rollouts(mock_flag, variants, environment)

        non_boolean_variants: list[PostHogVariantDict] = []
        for variant in variants:
            value = variant.get("value")
            variant_key = variant.get("key", "")

            if value not in [True, False, "true", "false"]:
                rollout_pct = variant_rollouts.get(variant_key, 0)
                non_boolean_variants.append(
                    {
                        "key": variant_key,
                        "name": variant.get("name", ""),
                        "rollout_percentage": rollout_pct,
                    }
                )

        if non_boolean_variants:
            return {"multivariate": {"variants": non_boolean_variants}}
        return None

    def extract_conditions(
        self, external_flag: dict[str, Any], environment: str, team: "Team | None"
    ) -> list[ConditionDict]:
        """Extract conditions from LaunchDarkly flag"""
        raw_environments = external_flag.get("metadata", {}).get("raw_environments")
        if raw_environments:
            key = external_flag.get("key", "")
            mock_raw_flag = {
                "key": key,
                "environments": raw_environments,
                "metadata": external_flag.get("metadata", {}),
            }
            import_api_key = external_flag.get("metadata", {}).get("api_key")
            import_project_key = external_flag.get("metadata", {}).get("project_key")

            return self.transform_conditions(mock_raw_flag, environment, import_api_key, import_project_key, team)
        return []

    def get_external_key_from_property(self, prop: PropertyDict) -> str | None:
        """Extract the external field key from a LaunchDarkly property"""
        return prop.get("external_key") or prop.get("key")


class LaunchDarklyRateLimiter:
    """Handles LaunchDarkly API rate limiting with exponential backoff and jitter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def make_request_with_rate_limiting(self, url: str, headers: dict, timeout: int = 30, max_retries: int = 3):
        """
        Make a request with proper rate limiting and exponential backoff.

        Returns:
            tuple: (response, success) where response is the requests.Response object
                   and success is a boolean indicating if the request was successful
        """
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                if response.status_code == 429:
                    wait_time = self._calculate_backoff_time(attempt, response)
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        time.sleep(wait_time)
                        continue
                    else:
                        return response, False

                else:
                    return response, True

            except Exception:
                if attempt == max_retries - 1:
                    raise
                wait_time = self._calculate_backoff_time(attempt)
                time.sleep(wait_time)

        raise Exception(f"Failed to complete request to {url} after {max_retries} attempts")

    def _calculate_backoff_time(self, attempt: int, response=None) -> float:
        """
        Calculate backoff time using exponential backoff with jitter.

        Args:
            attempt: The attempt number (0-based)
            response: Optional response object to check for Retry-After header

        Returns:
            float: Time to wait in seconds
        """
        # Check for Retry-After header first (LaunchDarkly recommendation)
        if response and response.headers.get("Retry-After"):
            try:
                retry_after = int(response.headers["Retry-After"])
                return retry_after
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid Retry-After header: {response.headers.get('Retry-After')}")

        base_delay = 1.0
        exponential_delay = base_delay * (2**attempt)
        exponential_delay = min(exponential_delay, 60.0)
        return exponential_delay
