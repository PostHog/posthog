#!/usr/bin/env python3
import json
import argparse

import pytest

from sync_clickhouse import (
    SKIP_SETTINGS,
    cmd_build_pr_body,
    cmd_sync_settings,
    cmd_sync_versions,
    compare_settings,
    extract_setting_from_xml,
    get_all_settings_from_default_profile,
    update_setting_in_file,
)


@pytest.fixture
def sample_prod_xml():
    return """<?xml version="1.0"?>
<yandex>
    <profiles>
        <default>
            <compatibility>25.6</compatibility>
            <enable_analyzer>0</enable_analyzer>
            <distributed_product_mode>global</distributed_product_mode>
            <max_memory_usage>10000000000</max_memory_usage>
            <custom_setting>custom_value</custom_setting>
        </default>
    </profiles>
</yandex>
"""


@pytest.fixture
def sample_local_xml():
    return """<?xml version="1.0"?>
<yandex>
    <profiles>
        <default>
            <compatibility>25.6</compatibility>
            <enable_analyzer>1</enable_analyzer>
            <distributed_product_mode>global</distributed_product_mode>
        </default>
    </profiles>
</yandex>
"""


@pytest.fixture
def sample_docker_compose():
    return """
services:
  clickhouse:
    image: clickhouse/clickhouse-server:25.3.1.1
"""


@pytest.fixture
def sample_versions_json():
    return {
        "production_eu": "clickhouse/clickhouse-server:25.4.2.1",
        "production_us": "clickhouse/clickhouse-server:25.3.1.1",
        "local": "clickhouse/clickhouse-server:25.3.1.1",
        "oldest_supported": "clickhouse/clickhouse-server:25.3.1.1",
    }


@pytest.mark.parametrize(
    "setting,expected",
    [
        ("compatibility", "25.6"),
        ("enable_analyzer", "0"),
        ("distributed_product_mode", "global"),
        ("nonexistent", None),
    ],
)
def test_extract_setting_from_xml(sample_prod_xml, setting, expected):
    assert extract_setting_from_xml(sample_prod_xml, setting) == expected


@pytest.mark.parametrize("invalid_xml", ["", "not valid xml <><>", "<unclosed>"])
def test_extract_setting_from_xml_handles_invalid_xml(invalid_xml):
    assert extract_setting_from_xml(invalid_xml, "compatibility") is None


def test_get_all_settings_extracts_non_skip_settings(sample_prod_xml):
    settings = get_all_settings_from_default_profile(sample_prod_xml)
    assert settings == {
        "compatibility": "25.6",
        "enable_analyzer": "0",
        "distributed_product_mode": "global",
        "custom_setting": "custom_value",
    }
    for skip_setting in SKIP_SETTINGS:
        assert skip_setting not in settings


def test_get_all_settings_handles_invalid_xml():
    assert get_all_settings_from_default_profile("invalid xml") == {}


def test_update_setting_in_file_updates_value(tmp_path, sample_local_xml):
    file_path = tmp_path / "test.xml"
    file_path.write_text(sample_local_xml)

    assert "<enable_analyzer>1</enable_analyzer>" in file_path.read_text()
    result = update_setting_in_file(file_path, "enable_analyzer", "0")

    assert result is True
    assert "<enable_analyzer>0</enable_analyzer>" in file_path.read_text()


def test_update_setting_in_file_no_change_when_same_value(tmp_path, sample_local_xml):
    file_path = tmp_path / "test.xml"
    file_path.write_text(sample_local_xml)

    assert "<compatibility>25.6</compatibility>" in file_path.read_text()
    result = update_setting_in_file(file_path, "compatibility", "25.6")

    assert result is True
    assert "<compatibility>25.6</compatibility>" in file_path.read_text()


def test_update_setting_in_file_returns_false_when_missing(tmp_path, sample_local_xml):
    file_path = tmp_path / "test.xml"
    file_path.write_text(sample_local_xml)

    assert "nonexistent_setting" not in file_path.read_text()
    result = update_setting_in_file(file_path, "nonexistent_setting", "value")

    assert result is False


def test_update_setting_in_file_skips_empty_value(tmp_path, sample_local_xml):
    file_path = tmp_path / "test.xml"
    file_path.write_text(sample_local_xml)

    assert "<compatibility>25.6</compatibility>" in file_path.read_text()
    result = update_setting_in_file(file_path, "compatibility", "")

    assert result is False
    assert "<compatibility>25.6</compatibility>" in file_path.read_text()


def test_compare_settings(sample_prod_xml, sample_local_xml):
    result = compare_settings(sample_prod_xml, sample_local_xml)

    assert result.prod_settings == {
        "compatibility": "25.6",
        "enable_analyzer": "0",
        "distributed_product_mode": "global",
    }
    assert result.mismatches == ["- `enable_analyzer`: production=`0`,local=`1`"]
    assert result.additional_settings == ["- `custom_setting`: production=`custom_value`, local=`not set`"]


def test_compare_settings_no_mismatch_when_equal(sample_prod_xml):
    result = compare_settings(sample_prod_xml, sample_prod_xml)

    assert result.mismatches == []
    assert result.additional_settings == []


def test_cmd_sync_versions_writes_json_output(tmp_path, sample_docker_compose):
    docker_file = tmp_path / "docker-compose.yml"
    docker_file.write_text(sample_docker_compose)
    output_file = tmp_path / "versions.json"

    args = argparse.Namespace(
        prod_eu_content="clickhouse_version: 25.4.2.1",
        prod_us_content='image = "clickhouse/clickhouse-server:25.4.1.1"',
        local_file=str(docker_file),
        output_file=str(output_file),
    )

    result = cmd_sync_versions(args)

    assert result == 0
    output = json.loads(output_file.read_text())
    assert output["production_eu"] == "clickhouse/clickhouse-server:25.4.2.1"
    assert output["production_us"] == "clickhouse/clickhouse-server:25.4.1.1"
    assert output["local"] == "clickhouse/clickhouse-server:25.3.1.1"
    assert output["oldest_supported"] == "clickhouse/clickhouse-server:25.4.1.1"


def test_cmd_sync_versions_ignores_ips_and_cidrs(tmp_path, sample_docker_compose):
    docker_file = tmp_path / "docker-compose.yml"
    docker_file.write_text(sample_docker_compose)
    output_file = tmp_path / "versions.json"

    # Content with IPs before the actual ClickHouse version
    args = argparse.Namespace(
        prod_eu_content="network: 10.0.0.1/24\nclickhouse_version: 25.4.2.1",
        prod_us_content="host: 192.168.1.100\nclickhouse/clickhouse-server:25.4.1.1",
        local_file=str(docker_file),
        output_file=str(output_file),
    )

    result = cmd_sync_versions(args)

    assert result == 0
    output = json.loads(output_file.read_text())
    assert output["production_eu"] == "clickhouse/clickhouse-server:25.4.2.1"
    assert output["production_us"] == "clickhouse/clickhouse-server:25.4.1.1"


def test_cmd_sync_versions_returns_error_on_missing_version(tmp_path, sample_docker_compose):
    docker_file = tmp_path / "docker-compose.yml"
    docker_file.write_text(sample_docker_compose)
    output_file = tmp_path / "versions.json"

    args = argparse.Namespace(
        prod_eu_content="no version here",
        prod_us_content="also no version",
        local_file=str(docker_file),
        output_file=str(output_file),
    )

    result = cmd_sync_versions(args)

    assert result == 1


def test_cmd_sync_settings_updates_files(tmp_path, sample_prod_xml, sample_local_xml):
    file1 = tmp_path / "users-dev.xml"
    file2 = tmp_path / "users.xml"
    file1.write_text(sample_local_xml)
    file2.write_text(sample_local_xml)

    args = argparse.Namespace(
        prod_xml=sample_prod_xml,
        local_files=f"{file1},{file2}",
    )

    assert "<enable_analyzer>1</enable_analyzer>" in file1.read_text()
    assert "<enable_analyzer>1</enable_analyzer>" in file2.read_text()
    result = cmd_sync_settings(args)

    assert result == 0
    assert "<enable_analyzer>0</enable_analyzer>" in file1.read_text()
    assert "<enable_analyzer>0</enable_analyzer>" in file2.read_text()


def test_cmd_sync_settings_returns_error_when_file_missing(tmp_path, sample_prod_xml):
    args = argparse.Namespace(
        prod_xml=sample_prod_xml,
        local_files=str(tmp_path / "nonexistent.xml"),
    )

    result = cmd_sync_settings(args)

    assert result == 1


EXPECTED_PR_BODY = """\
Automated sync of ClickHouse versions and settings from posthog-cloud-infra.

**Current versions:**
| Environment | Version |
|-------------|---------|
| Production EU | `25.4.2.1` |
| Production US | `25.3.1.1` |
| Local | `25.3.1.1` |
| Oldest Supported on prod | `25.3.1.1` |

**Synced settings:**
| Setting | Production Value |
|---------|-----------------|
| `enable_analyzer` | `0` |

**⚠️ Settings that differ from production:**
- `enable_analyzer`: mismatch

**🚨 Settings missing from local config files (need to be added manually):**
- `new_setting`: missing

**ℹ️ Additional production settings (not synced, should be reviewed as part of this pr):**
- `custom_setting`: additional

**Files updated:**
- `.github/clickhouse-versions.json` - version definitions (source of truth)
- `docker/clickhouse/users-dev.xml` - CI/dev ClickHouse config
- `docker/clickhouse/users.xml` - hobby deploy ClickHouse config

The "oldest_supported" version is the minimum across production environments and is used as the primary compatibility target in CI. If tests pass on the oldest supported version, they should work everywhere.

This PR was automatically created by the daily sync workflow."""


def test_cmd_build_pr_body_generates_complete_output(tmp_path, sample_versions_json, capsys):
    versions_file = tmp_path / "versions.json"
    versions_file.write_text(json.dumps(sample_versions_json))

    args = argparse.Namespace(
        versions_file=str(versions_file),
        settings_json='{"enable_analyzer": "0"}',
        mismatches="- `enable_analyzer`: mismatch",
        missing_settings="- `new_setting`: missing",
        additional_settings="- `custom_setting`: additional",
    )

    result = cmd_build_pr_body(args)

    assert result == 0
    captured = capsys.readouterr()
    # github_output prints "  key=value" when GITHUB_OUTPUT env var is not set
    assert captured.out.strip() == f"body={EXPECTED_PR_BODY}"
