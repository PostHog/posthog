from datetime import timedelta
from textwrap import dedent

import pytest

from products.data_modeling.backend.services.gitsync.config_parser import (
    TomlFormat,
    YamlFormat,
    format_for_path,
    parse_dag_config,
    parse_project_config,
    serialize_dag_config,
    serialize_project_config,
)


class TestParseProjectConfig:
    def test_minimal_config(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1
        """)
        result = parse_project_config(content)
        assert result.name == "Acme"
        assert result.version == 1
        assert len(result.environments) == 1
        assert result.environments[0].name == "production"
        assert result.models_directory == "models"

    def test_single_environment(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environment]
            name = "staging"
        """)
        result = parse_project_config(content)
        assert len(result.environments) == 1
        assert result.environments[0].name == "staging"
        assert result.is_multi_environment is False

    def test_multi_environment(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environments.production]
            name = "production"

            [environments.staging]
            name = "staging"

            [environments.dev]
            name = "dev"
        """)
        result = parse_project_config(content)
        assert len(result.environments) == 3
        assert result.is_multi_environment is True
        env_names = {e.name for e in result.environments}
        assert env_names == {"production", "staging", "dev"}

    def test_custom_models_directory(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [settings]
            models_directory = "sql/models"
        """)
        result = parse_project_config(content)
        assert result.models_directory == "sql/models"

    def test_environment_name_defaults_to_key(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environments.prod]
            """)
        result = parse_project_config(content)
        assert result.environments[0].name == "prod"


class TestParseProjectConfigValidation:
    def test_invalid_toml_raises(self):
        with pytest.raises(ValueError, match="Invalid posthog config"):
            parse_project_config("not [valid toml")

    def test_missing_project_section_raises(self):
        content = dedent("""\
            [settings]
            models_directory = "models"
        """)
        with pytest.raises(ValueError, match="must have a \\[project\\] section"):
            parse_project_config(content)

    def test_missing_project_name_raises(self):
        content = dedent("""\
            [project]
            version = 1
        """)
        with pytest.raises(ValueError, match="must have a name"):
            parse_project_config(content)

    def test_unsupported_version_raises(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 99
        """)
        with pytest.raises(ValueError, match="Unsupported.*version 99"):
            parse_project_config(content)

    def test_both_environment_and_environments_raises(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environment]
            name = "prod"

            [environments.staging]
            name = "staging"
        """)
        with pytest.raises(ValueError, match="mutually exclusive"):
            parse_project_config(content)

    def test_unknown_section_raises(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [database]
            host = "localhost"
        """)
        with pytest.raises(ValueError, match="Unknown sections.*database"):
            parse_project_config(content)

    def test_duplicate_environment_names_raises(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environments.prod1]
            name = "production"

            [environments.prod2]
            name = "production"
        """)
        with pytest.raises(ValueError, match="Duplicate environment names.*production"):
            parse_project_config(content)

    def test_empty_environments_table_raises(self):
        content = dedent("""\
            [project]
            name = "Acme"
            version = 1

            [environments]
        """)
        with pytest.raises(ValueError, match="at least one environment"):
            parse_project_config(content)

    @pytest.mark.parametrize(
        "content, match",
        [
            pytest.param(
                '[project]\nname = "Acme"\nversion = "1"',
                "version must be an integer",
                id="version_wrong_type",
            ),
            pytest.param(
                '[project]\nname = "Acme"\nversion = 1\n\n[environment]\nname = 42',
                "name must be a string",
                id="environment_name_wrong_type",
            ),
            pytest.param(
                '[project]\nname = "Acme"\nversion = 1\n\n[environments.prod]\nname = 42',
                "name must be a string",
                id="environments_name_wrong_type",
            ),
            pytest.param(
                '[project]\nname = "Acme"\nversion = 1\n\n[settings]\nmodels_directory = 42',
                "models_directory must be a string",
                id="models_directory_wrong_type",
            ),
        ],
    )
    def test_wrong_type_raises(self, content: str, match: str):
        with pytest.raises(ValueError, match=match):
            parse_project_config(content)


class TestParseDagConfig:
    def test_minimal_config(self):
        result = parse_dag_config("")
        assert result.sync_frequency == "1d"
        assert result.description == ""

    def test_with_sync_frequency(self):
        result = parse_dag_config('sync_frequency = "1h"')
        assert result.sync_frequency == "1h"

    def test_with_description(self):
        result = parse_dag_config('description = "Core metrics"')
        assert result.description == "Core metrics"

    def test_with_name(self):
        result = parse_dag_config('name = "Finance Pipeline"')
        assert result.name == "Finance Pipeline"

    def test_full_config(self):
        content = dedent("""\
            description = "Core business metrics"
            sync_frequency = "6h"
        """)
        result = parse_dag_config(content)
        assert result.description == "Core business metrics"
        assert result.sync_frequency == "6h"

    def test_sync_frequency_interval(self):
        result = parse_dag_config('sync_frequency = "1h"')
        assert result.sync_frequency_interval == timedelta(hours=1)

    @pytest.mark.parametrize("freq", ["15m", "30m", "1h", "6h", "12h", "24h", "1d", "7d", "30d"])
    def test_all_valid_frequencies(self, freq):
        result = parse_dag_config(f'sync_frequency = "{freq}"')
        assert result.sync_frequency == freq
        assert result.sync_frequency_interval is not None


class TestParseDagConfigValidation:
    def test_invalid_toml_raises(self):
        with pytest.raises(ValueError, match="Invalid dag config"):
            parse_dag_config("not valid toml [")

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="Unknown keys.*schedule"):
            parse_dag_config('schedule = "* * * * *"')

    def test_invalid_sync_frequency_raises(self):
        with pytest.raises(ValueError, match="Invalid sync_frequency"):
            parse_dag_config('sync_frequency = "2h"')

    @pytest.mark.parametrize(
        "content, match",
        [
            pytest.param("sync_frequency = 60", "sync_frequency must be a string", id="sync_frequency_wrong_type"),
            pytest.param("description = 42", "description must be a string", id="description_wrong_type"),
        ],
    )
    def test_wrong_type_raises(self, content: str, match: str):
        with pytest.raises(ValueError, match=match):
            parse_dag_config(content)


class TestSerializeProjectConfig:
    def test_single_environment(self):
        result = serialize_project_config(name="Acme")
        parsed = parse_project_config(result)
        assert parsed.name == "Acme"
        assert parsed.version == 1
        assert len(parsed.environments) == 1
        assert parsed.environments[0].name == "production"

    def test_multi_environment(self):
        result = serialize_project_config(
            name="Acme",
            environments=["production", "staging"],
        )
        parsed = parse_project_config(result)
        assert parsed.is_multi_environment is True
        env_names = {e.name for e in parsed.environments}
        assert env_names == {"production", "staging"}

    def test_custom_models_directory(self):
        result = serialize_project_config(name="Acme", models_directory="sql/views")
        parsed = parse_project_config(result)
        assert parsed.models_directory == "sql/views"


class TestSerializeDagConfig:
    def test_default(self):
        result = serialize_dag_config()
        parsed = parse_dag_config(result)
        assert parsed.sync_frequency == "1d"
        assert parsed.description == ""

    def test_with_all_fields(self):
        result = serialize_dag_config(sync_frequency="1h", description="Core metrics")
        parsed = parse_dag_config(result)
        assert parsed.sync_frequency == "1h"
        assert parsed.description == "Core metrics"


class TestFormatForPath:
    @pytest.mark.parametrize(
        "path, expected_label",
        [
            ("posthog.toml", "toml"),
            ("dag.toml", "toml"),
            ("posthog.yaml", "yaml"),
            ("posthog.yml", "yaml"),
            ("models/finance/dag.YAML", "yaml"),
            ("models/finance/dag.YML", "yaml"),
        ],
    )
    def test_detects_format_from_extension(self, path: str, expected_label: str):
        assert format_for_path(path).label == expected_label

    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported config file extension"):
            format_for_path("posthog.json")


class TestParseProjectConfigYaml:
    def test_minimal_yaml_config(self):
        content = dedent("""\
            project:
              name: Acme
              version: 1
        """)
        result = parse_project_config(content, format=YamlFormat())
        assert result.name == "Acme"
        assert result.version == 1
        assert result.environments[0].name == "production"

    def test_multi_environment_yaml(self):
        content = dedent("""\
            project:
              name: Acme
              version: 1
            environments:
              production:
                name: production
              staging:
                name: staging
        """)
        result = parse_project_config(content, format=YamlFormat())
        assert result.is_multi_environment is True
        assert {e.name for e in result.environments} == {"production", "staging"}

    def test_invalid_yaml_raises(self):
        with pytest.raises(ValueError, match="Invalid posthog config"):
            parse_project_config("project: [unclosed", format=YamlFormat())

    def test_non_mapping_top_level_raises(self):
        with pytest.raises(ValueError, match="Invalid posthog config.*mapping"):
            parse_project_config("- just\n- a\n- list\n", format=YamlFormat())

    def test_unknown_section_yaml_raises(self):
        content = dedent("""\
            project:
              name: Acme
              version: 1
            database:
              host: localhost
        """)
        with pytest.raises(ValueError, match="Unknown sections.*database"):
            parse_project_config(content, format=YamlFormat())

    def test_yaml_validation_shares_logic_with_toml(self):
        content = dedent("""\
            project:
              name: Acme
              version: "1"
        """)
        with pytest.raises(ValueError, match="version must be an integer"):
            parse_project_config(content, format=YamlFormat())


class TestParseDagConfigYaml:
    def test_full_yaml_config(self):
        content = dedent("""\
            name: Finance Pipeline
            sync_frequency: 6h
            description: Core business metrics
        """)
        result = parse_dag_config(content, format=YamlFormat())
        assert result.name == "Finance Pipeline"
        assert result.sync_frequency == "6h"
        assert result.description == "Core business metrics"

    def test_empty_yaml_uses_defaults(self):
        result = parse_dag_config("", format=YamlFormat())
        assert result.sync_frequency == "1d"

    def test_unknown_key_yaml_raises(self):
        with pytest.raises(ValueError, match="Unknown keys.*schedule"):
            parse_dag_config('schedule: "* * * * *"', format=YamlFormat())


class TestSerializeYaml:
    def test_serialize_project_yaml_round_trip(self):
        result = serialize_project_config(
            name="Acme",
            environments=["production", "staging"],
            format=YamlFormat(),
        )
        parsed = parse_project_config(result, format=YamlFormat())
        assert parsed.name == "Acme"
        assert parsed.is_multi_environment is True
        assert {e.name for e in parsed.environments} == {"production", "staging"}

    def test_serialize_dag_yaml_round_trip(self):
        result = serialize_dag_config(
            name="Finance",
            sync_frequency="1h",
            description="Core metrics",
            format=YamlFormat(),
        )
        parsed = parse_dag_config(result, format=YamlFormat())
        assert parsed.name == "Finance"
        assert parsed.sync_frequency == "1h"
        assert parsed.description == "Core metrics"


class TestStrategySymmetry:
    """Same data parses identically through any format."""

    @pytest.mark.parametrize(
        "toml_content, yaml_content",
        [
            pytest.param(
                '[project]\nname = "Acme"\nversion = 1\n',
                "project:\n  name: Acme\n  version: 1\n",
                id="minimal",
            ),
            pytest.param(
                dedent("""\
                    [project]
                    name = "Acme"
                    version = 1

                    [environments.prod]
                    name = "production"

                    [environments.stg]
                    name = "staging"

                    [settings]
                    models_directory = "sql"
                """),
                dedent("""\
                    project:
                      name: Acme
                      version: 1
                    environments:
                      prod:
                        name: production
                      stg:
                        name: staging
                    settings:
                      models_directory: sql
                """),
                id="full",
            ),
        ],
    )
    def test_project_config_equivalent(self, toml_content: str, yaml_content: str):
        toml_parsed = parse_project_config(toml_content, format=TomlFormat())
        yaml_parsed = parse_project_config(yaml_content, format=YamlFormat())
        assert toml_parsed == yaml_parsed
