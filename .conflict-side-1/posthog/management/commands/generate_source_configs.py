import os
import logging
from typing import Any, Optional

from django.core.management.base import BaseCommand

from structlog import get_logger

from posthog.schema import (
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.warehouse.types import ExternalDataSourceType

logger = get_logger(__name__)
logger.setLevel(logging.INFO)


# Generates `@config.Config` dataclasses to be used by sources to parse inputs from the frontend.
# The source of the configs come from the sources `get_source_config()` method (inherited from `BaseSource`).
# For an example, look at posthog/temporal/data_imports/sources/stripe/source.py

# This file shouldn't often need to be updated unless if we extend what fields sources can have.
# There exists a test file here: posthog/temporal/data_imports/sources/common/test/test_source_config_generator.py

# To start SourceConfigGenerator, run `pnpm generate:source-configs`

# Leftover TODO:
# - allow custom converter options (see meta ads and google ads source)
# - define metadata to add fields onto the config that come from settings, e.g:
#       field: str = config.value(default_factory=config.default_from_settings("ENV_VAR"))
# - Allow types to be given in `SourceFieldFileUploadJsonFormatConfig`


class SourceConfigGenerator:
    def __init__(self):
        self.generated_classes: dict[str, str] = {}
        self.imports: set[str] = set()
        self.typing_import: set[str] = set()
        self.nested_configs: dict[str, str] = {}

    def generate_all_configs(self) -> str:
        try:
            sources = SourceRegistry.get_all_sources()
            configs = {name: source.get_source_config for name, source in sources.items()}

            for source_type, source_config in configs.items():
                logger.info(f"Generating config for {source_type}")
                self.generate_source_config(source_type, source_config)
        except Exception as e:
            logger.exception(f"Error generating config: {e}")
            raise

        return self._build_output()

    def generate_source_config(self, source_type: ExternalDataSourceType, source_config: SourceConfig) -> None:
        self.imports.update(
            [
                "from posthog.temporal.data_imports.sources.common import config",
                "from posthog.warehouse.types import ExternalDataSourceType",
            ]
        )

        class_name = self._get_config_class_name(source_type)
        fields = []
        nested_classes = []

        for field in source_config.fields:
            field_defs, nested = self._process_field(field, class_name, source_config)
            if field_defs:
                fields.extend(field_defs)
            if nested:
                nested_classes.extend(nested)

        config_class = self._generate_config_class(class_name, fields)

        for nested_class in nested_classes:
            nested_name = self._extract_class_name(nested_class)
            self.nested_configs[nested_name] = nested_class

        self.generated_classes[class_name] = config_class

    def _process_field(self, field: Any, parent_class: str, source_config: SourceConfig) -> tuple[list[str], list[str]]:
        """Process a single field and return field definitions and any nested classes."""

        if isinstance(field, SourceFieldInputConfig):
            field_def = self._process_input_field(field)
            return [field_def] if field_def else [], []

        elif isinstance(field, SourceFieldSelectConfig):
            return self._process_select_field(field, parent_class, source_config)

        elif isinstance(field, SourceFieldSwitchGroupConfig):
            field_def, nested_classes = self._process_switch_group_field(field, parent_class, source_config)
            return [field_def] if field_def else [], nested_classes

        elif isinstance(field, SourceFieldOauthConfig):
            field_def = self._process_oauth_field(field)
            return [field_def] if field_def else [], []

        elif isinstance(field, SourceFieldFileUploadConfig):
            field_def, nested_class = self._process_file_upload_field(field, parent_class)
            return [field_def] if field_def else [], [nested_class]

        elif isinstance(field, SourceFieldSSHTunnelConfig):
            field_def = self._process_ssh_tunnel_field(field)
            return [field_def] if field_def else [], []

        else:
            logger.info(f"Unknown field type: {type(field)}")
            return [], []

    def _process_input_field(self, field: SourceFieldInputConfig) -> str:
        python_type = self._get_python_type(field.type)

        is_optional = not field.required
        if is_optional:
            python_type = f"{python_type} | None"

        field_parts = []

        converter = self._get_input_converter(field.type)
        if converter:
            field_parts.append(f"converter={converter}")

        python_field_name, should_alias = self._make_python_identifier(field.name)

        if should_alias:
            field_parts.append(f'alias="{field.name}"')

        if not field.required:
            if field_parts:
                field_parts.append("default_factory=lambda: None")
            else:
                field_def = f"    {python_field_name}: {python_type} = None"
                return field_def

        if field_parts:
            config_value = f"config.value({', '.join(field_parts)})"
            field_def = f"    {python_field_name}: {python_type} = {config_value}"
        else:
            field_def = f"    {python_field_name}: {python_type}"

        return field_def

    def _process_select_field(
        self, field: SourceFieldSelectConfig, parent_class: str, source_config: SourceConfig
    ) -> tuple[list[str], list[str]]:
        has_option_fields = any(option.fields for option in field.options if option.fields)

        field_parts = []

        if not field.required and not field.defaultValue:
            field_parts.append("default_factory=lambda: None")

        if field.defaultValue:
            if field.converter:
                field_parts.append(f'default=config.{field.converter.value}("{field.defaultValue}")')
            else:
                field_parts.append(f'default="{field.defaultValue}"')

        if field.converter:
            field_parts.append(f"converter=config.{field.converter.value}")

        if not has_option_fields:
            literal_type = self._get_select_literal_type(field)

            python_field_name, should_alias = self._make_python_identifier(field.name)

            if should_alias:
                field_parts.append(f'alias="{field.name}"')

            if not field.required:
                literal_type = f"{literal_type} | None"

            if field_parts:
                config_value = f"config.value({', '.join(field_parts)})"
                field_def = f"    {python_field_name}: {literal_type} = {config_value}"
            else:
                field_def = f"    {python_field_name}: {literal_type}"

            return [field_def], []

        nested_classes = []

        # Nested behavior - create nested structure
        nested_class_name = self._get_nested_class_name(field.name, parent_class)

        nested_field_defs = []

        literal_type = self._get_select_literal_type(field)

        if field.defaultValue:
            nested_field_defs.append(f'    selection: {literal_type} = "{field.defaultValue}"')
        else:
            nested_field_defs.append(f"    selection: {literal_type}")

        seen_field_names = set()

        for option in field.options:
            if not option.fields:
                continue

            for option_field in option.fields:
                field_defs, nested = self._process_field(option_field, nested_class_name, source_config)
                if field_defs:
                    for field_def in field_defs:
                        field_name = field_def.split(":")[0].strip()
                        if field_name not in seen_field_names:
                            nested_field_defs.extend(field_defs)
                            seen_field_names.add(field_name)
                if nested:
                    nested_classes.extend(nested)

        nested_config = self._generate_config_class(nested_class_name, nested_field_defs)
        nested_classes.append(nested_config)

        python_field_name, should_alias = self._make_python_identifier(field.name)

        if should_alias:
            if field.required:
                parent_field = f'    {python_field_name}: {nested_class_name} = config.value(alias="{field.name}")'
            else:
                parent_field = f'    {python_field_name}: {nested_class_name} | None = config.value(alias="{field.name}", default_factory=lambda: None)'
        else:
            if field.required:
                parent_field = f"    {python_field_name}: {nested_class_name}"
            else:
                parent_field = f"    {python_field_name}: {nested_class_name} | None = None"

        return [parent_field], nested_classes

    def _process_switch_group_field(
        self, field: SourceFieldSwitchGroupConfig, parent_class: str, source_config: SourceConfig
    ) -> tuple[str, list[str]]:
        """Process a switch group field (like SSH tunnel)."""

        nested_class_name = self._get_nested_class_name(field.name, parent_class)

        nested_fields = ["    enabled: bool = config.value(converter=config.str_to_bool, default=False)"]

        nested_classes = []
        for sub_field in field.fields:
            field_defs, sub_nested = self._process_field(sub_field, nested_class_name, source_config)
            if field_defs:
                nested_fields.extend(field_defs)
            if sub_nested:
                nested_classes.extend(sub_nested)

        nested_config = self._generate_config_class(nested_class_name, nested_fields)
        nested_classes.append(nested_config)

        # Convert dashes to underscores for valid Python field names
        python_field_name, should_alias = self._make_python_identifier(field.name)

        if should_alias:
            # Use alias to map back to original field name with dashes
            field_def = f'    {python_field_name}: {nested_class_name} | None = config.value(alias="{field.name}", default_factory=lambda: None)'
        else:
            field_def = f"    {python_field_name}: {nested_class_name} | None = None"

        return field_def, nested_classes

    def _process_oauth_field(self, field: SourceFieldOauthConfig) -> str:
        python_field_name, should_alias = self._make_python_identifier(field.name)

        if field.required:
            if should_alias:
                return f'    {python_field_name}: int = config.value(alias="{field.name}", converter=config.str_to_int)'
            else:
                return f"    {python_field_name}: int = config.value(converter=config.str_to_int)"
        else:
            if should_alias:
                return f'    {python_field_name}: int | None = config.value(alias="{field.name}", converter=config.str_to_optional_int, default_factory=lambda: None)'
            else:
                return f"    {python_field_name}: int | None = config.value(converter=config.str_to_optional_int, default_factory=lambda: None)"

    def _process_file_upload_field(self, field: SourceFieldFileUploadConfig, parent_class: str) -> tuple[str, str]:
        python_field_name, should_alias = self._make_python_identifier(field.name)

        nested_config: str = ""
        literal_type = "dict[str, Any]"

        if isinstance(field.fileFormat.keys, list):
            nested_class_name = self._get_nested_class_name(field.name, parent_class)
            nested_field_defs = []
            for key in field.fileFormat.keys:
                nested_field_defs.append(f"    {key}: str")
            nested_config = self._generate_config_class(nested_class_name, nested_field_defs)
            literal_type = nested_class_name
        else:
            self.typing_import.add("Any")

        if field.required:
            if should_alias:
                return f'    {python_field_name}: {literal_type} = config.value(alias="{field.name}")', nested_config
            else:
                return f"    {python_field_name}: {literal_type}", nested_config
        else:
            if should_alias:
                return (
                    f'    {python_field_name}: {literal_type} | None = config.value(alias="{field.name}", default_factory=lambda: None)',
                    nested_config,
                )
            else:
                return f"    {python_field_name}: {literal_type} | None = None", nested_config

    def _process_ssh_tunnel_field(self, field: SourceFieldSSHTunnelConfig) -> str:
        """Process a SSH tunnel field by referencing the existing SSHTunnelConfig."""

        self.imports.add("from posthog.warehouse.models.ssh_tunnel import SSHTunnelConfig")

        python_field_name, should_alias = self._make_python_identifier(field.name)

        if should_alias:
            # Use alias to map back to original field name with dashes
            return f'    {python_field_name}: SSHTunnelConfig | None = config.value(alias="{field.name}", default_factory=lambda: None)'
        else:
            return f"    {python_field_name}: SSHTunnelConfig | None = None"

    def _get_python_type(self, field_type: SourceFieldInputConfigType) -> str:
        type_mapping = {
            SourceFieldInputConfigType.TEXT: "str",
            SourceFieldInputConfigType.PASSWORD: "str",
            SourceFieldInputConfigType.EMAIL: "str",
            SourceFieldInputConfigType.NUMBER: "int",
            SourceFieldInputConfigType.TEXTAREA: "str",
        }

        return type_mapping.get(field_type, "str")

    def _get_input_converter(self, field_type: SourceFieldInputConfigType) -> Optional[str]:
        converter_mapping = {
            SourceFieldInputConfigType.NUMBER: "int",
        }

        return converter_mapping.get(field_type)

    def _get_select_literal_type(self, field: SourceFieldSelectConfig) -> str:
        if not field.converter:
            option_values = [f'"{option.value}"' for option in field.options]
            self.typing_import.add("Literal")
            return f"Literal[{', '.join(option_values)}]"

        if field.converter == SourceFieldSelectConfigConverter.STR_TO_BOOL:
            return "bool"

        if field.converter == SourceFieldSelectConfigConverter.STR_TO_INT:
            return "int"

        if field.converter == SourceFieldSelectConfigConverter.STR_TO_OPTIONAL_INT:
            return "int | None"

        raise ValueError(f"Converter value {field.converter} not recognized")

    def _get_config_class_name(self, source_type: ExternalDataSourceType) -> str:
        return f"{source_type.value}SourceConfig"

    def _get_nested_class_name(self, field_name: str, parent_class: str) -> str:
        parent_prefix = parent_class.replace("SourceConfig", "")

        class_name_part = "".join(word.title() for word in field_name.replace("-", "_").split("_"))

        return f"{parent_prefix}{class_name_part}Config"

    def _sort_fields_by_defaults(self, fields: list[str]) -> list[str]:
        """Sort fields so that fields without defaults come before fields with defaults."""

        fields_without_defaults = []
        fields_with_config_annotations = []
        fields_with_none_default = []
        fields_with_defaults = []

        for field in fields:
            field_content = field.strip()
            if field_content == "pass" or not field_content:
                continue

            # If the field contains " = " it has a default, otherwise it doesn't
            if "config." in field_content and "default=" not in field_content:
                fields_with_config_annotations.append(field)
            elif " = " in field_content and "default_factory=lambda: None" in field_content:
                fields_with_none_default.append(field)
            elif " = " in field_content:
                fields_with_defaults.append(field)
            else:
                fields_without_defaults.append(field)

        return (
            fields_without_defaults + fields_with_config_annotations + fields_with_none_default + fields_with_defaults
        )

    def _generate_config_class(self, class_name: str, fields: list[str]) -> str:
        if fields:
            sorted_fields = self._sort_fields_by_defaults(fields)
            fields_str = "\n".join(sorted_fields)
        else:
            fields_str = "    pass"

        return f"""@config.config
class {class_name}(config.Config):
{fields_str}"""

    def _make_python_identifier(self, field_name: str) -> tuple[str, bool]:
        if "-" in field_name:
            return field_name.replace("-", "_"), True

        return field_name, False

    def _extract_class_name(self, class_definition: str) -> str:
        lines = class_definition.split("\n")
        for line in lines:
            if line.startswith("class "):
                return line.split("class ")[1].split("(")[0]
        return ""

    def _build_output(self) -> str:
        sources = SourceRegistry.get_all_sources()

        parts = []

        parts.append("# This file is automatically generated from `SourceRegistry.get_all_sources()`")
        parts.append("# Do not edit manually - run `pnpm generate:source-configs` to regenerate.")
        parts.append("")

        for import_line in sorted(self.imports):
            parts.append(import_line)
        if self.typing_import:
            parts.append(f"from typing import {', '.join(self.typing_import)}")
        parts.append("")
        parts.append("")

        for class_name in sorted(self.nested_configs.keys()):
            parts.append(self.nested_configs[class_name])
            parts.append("")
            parts.append("")

        for class_name in sorted(self.generated_classes.keys()):
            parts.append(self.generated_classes[class_name])
            parts.append("")
            parts.append("")

        parts.append("def get_config_for_source(source: ExternalDataSourceType):")
        parts.append("    return {")
        for source_type in sorted(sources.keys(), key=lambda x: x.value):
            config_class = self._get_config_class_name(source_type)
            parts.append(f"        ExternalDataSourceType.{source_type.name}: {config_class},")
        parts.append("    }[source]")
        parts.append("")

        return "\n".join(parts)


class Command(BaseCommand):
    help = "Generate @config.config classes from data warehouse source definitions"

    def handle(self, *args, **options):
        logger.info("Generating source configs from SourceRegistry...")

        generator = SourceConfigGenerator()
        output = generator.generate_all_configs()

        output_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "temporal", "data_imports", "sources", "generated_configs.py"
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            f.write(output)

        logger.info(f"Generated source configs written to: {output_path}")
        logger.info(f"Generated {len(generator.generated_classes)} main config classes")
        logger.info(f"Generated {len(generator.nested_configs)} nested config classes")
