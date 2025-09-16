from typing import cast

import pytest
from posthog.test.base import ClickhouseTestMixin

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    Option,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.management.commands.generate_source_configs import SourceConfigGenerator
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.warehouse.types import ExternalDataSourceType


class TestSourceConfigGenerator(ClickhouseTestMixin):
    def _run(self, sources: dict[ExternalDataSourceType, SourceConfig]) -> str:
        generator = SourceConfigGenerator()
        for name, config in sources.items():
            generator.generate_source_config(name, config)
        return generator._build_output()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_source_config_types(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="input_field",
                        label="input label",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="input placeholder",
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="switch_group",
                        label="switch group label",
                        caption="switch group caption",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="input_field_1",
                                    label="input label",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder="input placeholder",
                                ),
                                SourceFieldInputConfig(
                                    name="input_field_2",
                                    label="input label",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder="input placeholder",
                                ),
                            ],
                        ),
                    ),
                    SourceFieldSelectConfig(
                        name="select_with_options",
                        label="select label",
                        required=True,
                        defaultValue="1",
                        options=[Option(label="Yes", value="1"), Option(label="No", value="0")],
                    ),
                    SourceFieldSelectConfig(
                        name="select_with_fields",
                        label="select label",
                        required=True,
                        defaultValue="1",
                        options=[
                            Option(
                                label="option 1",
                                value="option_1",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="option_1_input",
                                            label="option_1 label",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="option_1 placeholder",
                                        ),
                                    ],
                                ),
                            ),
                            Option(
                                label="option 2",
                                value="option_2",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="option_2_input",
                                            label="option_2 label",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="option_2 placeholder",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldOauthConfig(
                        name="oauth_integration_id", label="oauth account", required=True, kind="source"
                    ),
                    SourceFieldFileUploadConfig(
                        name="file_upload",
                        label="file upload label",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(keys=["key_1", "key_2"]),
                        required=True,
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="ssh tunnel label"),
                ],
            ),
        )

        assert self._run({ExternalDataSourceType.STRIPE: config}) == self.snapshot

    def test_source_config_required(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="input_field",
                        label="input label",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="input placeholder",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert "input_field: str" in output
        assert "input_field: str | None = None" not in output

    def test_source_config_not_required(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="input_field",
                        label="input label",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="input placeholder",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert "input_field: str | None = None" in output

    def test_source_config_input_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="input-field",  # dashes are not allowed in python identifiers
                        label="input label",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="input placeholder",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert 'input_field: str = config.value(alias="input-field")' in output

    def test_source_config_switch_group_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSwitchGroupConfig(
                        name="switch-group",  # dashes are not allowed in python identifiers
                        label="switch group label",
                        caption="switch group caption",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="input-field-1",  # dashes are not allowed in python identifiers
                                    label="input label",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder="input placeholder",
                                ),
                            ],
                        ),
                    )
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert (
            'switch_group: StripeSwitchGroupConfig | None = config.value(alias="switch-group", default_factory=lambda: None)'
            in output
        )
        assert 'input_field_1: str | None = config.value(alias="input-field-1", default_factory=lambda: None)' in output

    def test_source_config_file_upload_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="file-upload",  # dashes are not allowed in python identifiers
                        label="file upload label",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(keys=["key_1", "key_2"]),
                        required=True,
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert 'file_upload: StripeFileUploadConfig = config.value(alias="file-upload")' in output
        assert "class StripeFileUploadConfig" in output
        assert "key_1: str" in output
        assert "key_2: str" in output

    def test_source_config_oauth_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="oauth-integration-id",  # dashes are not allowed in python identifiers
                        label="oauth account",
                        required=True,
                        kind="source",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert (
            'oauth_integration_id: int = config.value(alias="oauth-integration-id", converter=config.str_to_int)'
            in output
        )

    def test_source_config_ssh_tunnel_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSSHTunnelConfig(
                        name="ssh-tunnel",  # dashes are not allowed in python identifiers
                        label="ssh tunnel label",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert (
            'ssh_tunnel: SSHTunnelConfig | None = config.value(alias="ssh-tunnel", default_factory=lambda: None)'
            in output
        )

    def test_source_config_complex_select_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="select-with-fields",  # dashes are not allowed in python identifiers
                        label="select label",
                        required=True,
                        defaultValue="option_1",
                        options=[
                            Option(
                                label="option 1",
                                value="option_1",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="option-1-input",  # dashes are not allowed in python identifiers
                                            label="option_1 label",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="option_1 placeholder",
                                        ),
                                    ],
                                ),
                            ),
                            Option(
                                label="option 2",
                                value="option_2",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="option-2-input",  # dashes are not allowed in python identifiers
                                            label="option_2 label",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="option_2 placeholder",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    )
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert 'select_with_fields: StripeSelectWithFieldsConfig = config.value(alias="select-with-fields")' in output
        assert "class StripeSelectWithFieldsConfig(config.Config)" in output
        assert 'selection: Literal["option_1", "option_2"] = "option_1' in output
        assert 'option_1_input: str = config.value(alias="option-1-input")' in output
        assert 'option_2_input: str = config.value(alias="option-2-input")' in output

    def test_source_config_simple_select_non_python_identifier(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="select-with-options",  # dashes are not allowed in python identifiers
                        label="select label",
                        required=True,
                        defaultValue="1",
                        options=[Option(label="Yes", value="1"), Option(label="No", value="0")],
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert (
            'select_with_options: Literal["1", "0"] = config.value(default="1", alias="select-with-options")' in output
        )

    def test_source_config_ssh_tunnel_reference(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="ssh tunnel label"),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert "from posthog.warehouse.models.ssh_tunnel import SSHTunnelConfig" in output
        assert "ssh_tunnel: SSHTunnelConfig" in output

    def test_source_config_type_conversion(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="int_value",
                        label="int",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="12345",
                    ),
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert "int_value: int = config.value(converter=int)" in output

    def test_source_config_nested_class(self):
        config = SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            iconPath="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSwitchGroupConfig(
                        name="switch_group",
                        label="switch group label",
                        caption="switch group caption",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="input_field_1",
                                    label="input label",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder="input placeholder",
                                ),
                                SourceFieldInputConfig(
                                    name="input_field_2",
                                    label="input label",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=False,
                                    placeholder="input placeholder",
                                ),
                            ],
                        ),
                    )
                ],
            ),
        )

        output = self._run({ExternalDataSourceType.STRIPE: config})
        assert "class StripeSwitchGroupConfig(config.Config):" in output
        assert "switch_group: StripeSwitchGroupConfig" in output
