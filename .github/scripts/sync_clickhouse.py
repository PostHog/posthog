# !/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "defusedxml>=0.7.1",
# ]
# ///
# ruff: noqa: T201 - print statements are intentional for GitHub Actions workflow commands

import os
import re
import sys
import json
import argparse
from dataclasses import dataclass
from pathlib import Path

import defusedxml.ElementTree as ET

# Settings that affect query behavior - which we want to be kept in sync between prod and local
BEHAVIORAL_SETTINGS = [
    # Compatibility mode - locks behavior to a specific version
    "compatibility",
    # Query processing
    "enable_analyzer",
    "distributed_product_mode",
    "enable_parallel_replicas",
    "max_parallel_replicas",
    # Mutations
    "allow_nondeterministic_mutations",
    "number_of_mutations_to_throw",
    # Experimental features that affect query syntax/semantics
    "allow_experimental_window_functions",
    "allow_suspicious_low_cardinality_types",
    # INSERT behavior
    "insert_distributed_sync",
    "throw_on_max_partitions_per_insert_block",
]

# Settings to skip when scanning for unknown settings (performance-only, not behavioral)
SKIP_SETTINGS = {
    "max_memory_usage",
    "max_threads",
    "max_execution_time",
    "max_bytes_before_external_group_by",
    "max_rows_to_read",
    "max_bytes_to_read",
    "load_balancing",
    "profile",
    "readonly",
}


def github_output(key: str, value: str) -> None:
    github_output_file = os.environ.get("GITHUB_OUTPUT")

    if github_output_file:
        with open(github_output_file, "a") as f:
            if "\n" in value:
                # Use heredoc syntax for multiline values
                f.write(f"{key}<<EOF\n{value}\nEOF\n")
            else:
                f.write(f"{key}={value}\n")
    else:
        print(f"  {key}={value}")


def github_notice(message: str) -> None:
    print(f"::notice::{message}")


def github_warning(message: str) -> None:
    print(f"::warning::{message}")


def github_error(message: str) -> None:
    print(f"::error::{message}")


def extract_setting_from_xml(xml_content: str, setting: str) -> str | None:
    try:
        root = ET.fromstring(xml_content)
        elem = root.find(f".//profiles/default/{setting}")
        if elem is not None and elem.text:
            return elem.text.strip()
    except ET.ParseError:
        pass
    return None


def get_all_settings_from_default_profile(xml_content: str) -> dict[str, str]:
    settings = {}
    try:
        root = ET.fromstring(xml_content)
        default_profile = root.find(".//profiles/default")
        if default_profile is not None:
            for elem in default_profile:
                if elem.tag not in SKIP_SETTINGS and elem.text:
                    settings[elem.tag] = elem.text.strip()
    except ET.ParseError:
        pass
    return settings


def update_setting_in_file(file_path: Path, setting: str, new_value: str) -> bool:
    if not new_value:
        return False

    content = file_path.read_text()
    pattern = rf"<{setting}>([^<]*)</{setting}>"
    match = re.search(pattern, content)

    if match:
        current_value = match.group(1)
        if current_value != new_value:
            new_content = re.sub(pattern, f"<{setting}>{new_value}</{setting}>", content)
            file_path.write_text(new_content)
        return True
    return False


@dataclass
class SettingsComparison:
    prod_settings: dict[str, str]
    mismatches: list[str]
    additional_settings: list[str]


def compare_settings(prod_xml: str, local_xml: str) -> SettingsComparison:
    prod_settings = {}
    mismatches = []
    additional = []

    for setting in BEHAVIORAL_SETTINGS:
        prod_value = extract_setting_from_xml(prod_xml, setting)
        local_value = extract_setting_from_xml(local_xml, setting)

        if prod_value:
            prod_settings[setting] = prod_value

            if prod_value != local_value:
                mismatches.append(f"- `{setting}`: production=`{prod_value}`,local=`{local_value or 'not set'}`")
                github_warning(f"{setting}: production={prod_value}, local={local_value or 'NOT SET'}")

    # Scan for additional settings in production that differ from local
    all_prod_settings = get_all_settings_from_default_profile(prod_xml)
    for setting, prod_value in all_prod_settings.items():
        if setting in BEHAVIORAL_SETTINGS:
            continue

        local_value = extract_setting_from_xml(local_xml, setting)
        if prod_value != local_value:
            additional.append(f"- `{setting}`: production=`{prod_value}`, local=`{local_value or 'not set'}`")
            github_notice(f"{setting}: production={prod_value}, local={local_value or 'NOT SET'}")

    return SettingsComparison(
        prod_settings=prod_settings,
        mismatches=mismatches,
        additional_settings=additional,
    )


def cmd_sync_settings(args: argparse.Namespace) -> int:
    files = [Path(f.strip()) for f in args.local_files.split(",")]

    # Keep track of the differences across the files for the PR body.
    mismatches: set[str] = set()
    additional: set[str] = set()
    missing_settings: set[str] = set()
    prod_settings: dict[str, str] = {}

    for file_path in files:
        if not file_path.exists():
            github_warning(f"File not found: {file_path}")
            return 1

        result = compare_settings(args.prod_xml, file_path.read_text())
        prod_settings = result.prod_settings
        mismatches.update(result.mismatches)
        additional.update(result.additional_settings)

        # Sync behavioral settings only
        for setting, value in prod_settings.items():
            if not update_setting_in_file(file_path, setting, value):
                missing_settings.add(setting)

    github_output("settings_json", json.dumps(prod_settings))

    if mismatches:
        github_output("mismatches", "\n".join(sorted(mismatches)))

    if additional:
        github_output("additional_settings", "\n".join(sorted(additional)))

    if missing_settings:
        sorted_missing_settings = sorted(missing_settings)
        github_warning(f"Settings missing from local config files: {' '.join(sorted_missing_settings)}")
        missing_lines = [
            f"- `{setting}`: production=`{prod_settings.get(setting, 'unknown')}`"
            for setting in sorted_missing_settings
        ]
        github_output("missing_settings", "\n".join(missing_lines))

    return 0


def cmd_build_pr_body(args: argparse.Namespace) -> int:
    versions = json.loads(Path(args.versions_file).read_text())
    settings = json.loads(args.settings_json) if args.settings_json else {}

    def version_from_image(image: str) -> str:
        return image.split(":")[-1] if image else ""

    lines = [
        "Automated sync of ClickHouse versions and settings from posthog-cloud-infra.",
        "",
        "**Current versions:**",
        "| Environment | Version |",
        "|-------------|---------|",
        f"| Production EU | `{version_from_image(versions.get('production_eu', ''))}` |",
        f"| Production US | `{version_from_image(versions.get('production_us', ''))}` |",
        f"| Local | `{version_from_image(versions.get('local', ''))}` |",
        f"| Oldest Supported on prod | `{version_from_image(versions.get('oldest_supported', ''))}` |",
        "",
        "**Synced settings:**",
        "| Setting | Production Value |",
        "|---------|-----------------|",
    ]

    for setting, value in settings.items():
        lines.append(f"| `{setting}` | `{value}` |")

    if args.mismatches:
        lines.extend(["", "**⚠️ Settings that differ from production:**", args.mismatches])

    if args.missing_settings:
        lines.extend(
            ["", "**🚨 Settings missing from local config files (need to be added manually):**", args.missing_settings]
        )

    if args.additional_settings:
        lines.extend(
            [
                "",
                "**ℹ️ Additional production settings (not synced, should be reviewed as part of this pr):**",
                args.additional_settings,
            ]
        )

    lines.extend(
        [
            "",
            "**Files updated:**",
            "- `.github/clickhouse-versions.json` - version definitions (source of truth)",
            "- `docker/clickhouse/users-dev.xml` - CI/dev ClickHouse config",
            "- `docker/clickhouse/users.xml` - hobby deploy ClickHouse config",
            "",
            'The "oldest_supported" version is the minimum across production environments and is used as the primary compatibility target in CI. If tests pass on the oldest supported version, they should work everywhere.',
            "",
            "This PR was automatically created by the daily sync workflow.",
        ]
    )

    body = "\n".join(lines)
    github_output("body", body)
    return 0


def cmd_sync_versions(args: argparse.Namespace) -> int:
    errors = []

    def get_version(name: str, content: str) -> str | None:
        patterns = [
            r"clickhouse/clickhouse-server:(\d+\.\d+\.\d+(?:\.\d+)?)",  # Docker image (3 or 4 parts)
            r"clickhouse_version:\s*['\"]?(\d+\.\d+\.\d+(?:\.\d+)?)",  # Ansible variable
            r"clickhouse_version\s*=\s*['\"]?(\d+\.\d+\.\d+(?:\.\d+)?)",  # Terraform variable
        ]
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        errors.append(f"- **{name}**: Failed to extract ClickHouse version")
        return None

    prod_eu = get_version("Production EU", args.prod_eu_content)
    prod_us = get_version("Production US", args.prod_us_content)
    local_version = get_version("Local", Path(args.local_file).read_text())

    if errors:
        github_error("Failed to fetch ClickHouse versions. File paths in posthog-cloud-infra may have changed.")
        for error in errors:
            github_error(error)
        return 1

    # Compute the oldest supported version
    versions = sorted([v for v in [prod_eu, prod_us] if v], key=lambda v: list(map(int, v.split("."))))
    oldest_supported = versions[0] if versions else local_version

    output_data = {
        "production_eu": f"clickhouse/clickhouse-server:{prod_eu}" if prod_eu else "",
        "production_us": f"clickhouse/clickhouse-server:{prod_us}" if prod_us else "",
        "local": f"clickhouse/clickhouse-server:{local_version}" if local_version else "",
        "oldest_supported": f"clickhouse/clickhouse-server:{oldest_supported}" if oldest_supported else "",
    }
    Path(args.output_file).write_text(json.dumps(output_data, indent=2) + "\n")

    github_notice(
        f"Production EU: {prod_eu}, Production US: {prod_us}, Local: {local_version}, Oldest supported: {oldest_supported}"
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ClickHouse versions and settings from posthog-cloud-infra")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # sync-settings subcommand
    sync_settings_parser = subparsers.add_parser("sync-settings", help="Compare and sync ClickHouse settings")
    sync_settings_parser.add_argument("--prod-xml", required=True, help="Production users.xml content")
    sync_settings_parser.add_argument(
        "--local-files",
        required=True,
        help="Comma-separated list of local XML files to check against",
    )

    # sync-versions subcommand
    sync_versions_parser = subparsers.add_parser("sync-versions", help="Validate and sync ClickHouse versions")
    sync_versions_parser.add_argument(
        "--prod-eu-content", required=True, help="Raw content containing Production EU version"
    )
    sync_versions_parser.add_argument(
        "--prod-us-content", required=True, help="Raw content containing Production US version"
    )
    sync_versions_parser.add_argument(
        "--local-file", required=True, help="Path to docker-compose file to extract local version"
    )
    sync_versions_parser.add_argument("--output-file", required=True, help="Path to write clickhouse-versions.json")

    # build-pr-body subcommand
    pr_body_parser = subparsers.add_parser("build-pr-body", help="Build PR body markdown from sync outputs")
    pr_body_parser.add_argument("--versions-file", required=True, help="Path to clickhouse-versions.json")
    pr_body_parser.add_argument("--settings-json", default="", help="Settings JSON string")
    pr_body_parser.add_argument("--mismatches", default="", help="Mismatches markdown text")
    pr_body_parser.add_argument("--missing-settings", default="", help="Missing settings markdown text")
    pr_body_parser.add_argument("--additional-settings", default="", help="Additional settings markdown text")

    args = parser.parse_args()

    if args.command == "sync-settings":
        return cmd_sync_settings(args)
    elif args.command == "sync-versions":
        return cmd_sync_versions(args)
    elif args.command == "build-pr-body":
        return cmd_build_pr_body(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
