#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI script to verify all Django models with team/org/user FKs
are listed in the semgrep IDOR rule regex patterns.

Usage:
    python scripts/check_idor_model_coverage.py

Exit codes:
    0 - All models covered
    1 - Missing models found (ERROR)
"""

import os
import re
import sys
from pathlib import Path

import yaml


def setup_django() -> None:
    """Initialize Django settings for model introspection."""
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    sys.path.insert(0, repo_root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    import django

    django.setup()


def get_scoped_models() -> tuple[dict[str, set[str]], set[str]]:
    """
    Scan all Django models and categorize by scope.

    The semgrep rules use these categories:
        - team_scoped: models with team FK (primary IDOR protection)
        - org_scoped: models with organization FK (but not team)
        - user_scoped: models with user FK only (no team/org)

    Note: Models with both user and team FKs are treated as team_scoped
    since the team filter is the primary access control mechanism.

    Returns:
        Tuple of (scoped_models_dict, excluded_models_set)
    """
    from django.apps import apps
    from django.db.models import ForeignKey

    # Models to exclude from coverage checking.
    # Every entry here means "this model does NOT need to appear in semgrep IDOR rules."
    # When adding a model to a semgrep rule, remove it from here so CI verifies coverage.
    EXCLUDED_MODELS: set[str] = {
        # --- Core identity (not tenant-scoped themselves) ---
        "Organization",
        "Team",
        "User",
        # --- Abstract models / base classes (no table) ---
        "UUIDModel",
        "UUIDClassicModel",
        "CreatedMetaFields",
        "DeletedMetaFields",
        # --- Through/junction tables (access controlled by parent) ---
        "CohortPeople",
        "DashboardTile",
        "ExperimentToSavedMetric",
        "FeatureFlagHashKeyOverride",
        "GroupTypeMapping",
        "TaggedItem",
        "Tile",
        # --- Categorization mismatch ---
        # PersonalAPIKey has a deprecated team FK so the script sees it as team_scoped,
        # but the semgrep rule correctly lists it under user_scoped. Excluding prevents
        # a false "missing from team_scoped" error.
        "PersonalAPIKey",
        # RoleMembership has a direct user FK but org is indirect (via role), so the
        # script sees it as user_scoped while semgrep correctly has it in org_scoped.
        "RoleMembership",
        # --- Ingestion/event tables (not queried by user-supplied ID) ---
        "CoreEvent",
        "ElementGroup",
        "Event",
        "PersonlessDistinctId",
        "SessionRecordingEvent",
        # --- Persons system (managed separately, not looked up by user input) ---
        "Group",
        "PendingPersonOverride",
        "Person",
        "PersonDistinctId",
        "PersonOverride",
        "PersonOverrideMapping",
        # --- Schema/definition models (read-only, synced from events) ---
        "EventDefinition",
        "EventProperty",
        "PropertyDefinition",
        # --- Plugin system deprecated internals ---
        "PluginAttachment",
        "PluginLogEntry",
        "PluginSourceFile",
        "PluginStorage",
        # --- Third-party/external models ---
        "LogEntry",
        "OAuthAccessToken",
        "OAuthApplication",
        "OAuthGrant",
        "OAuthIDToken",
        "OAuthRefreshToken",
        "StaticDevice",
        "TOTPDevice",
        "UserSocialAuth",
        # --- Internal infra (audit, async, caching, scheduling) ---
        "ActivityLog",
        "AsyncDeletion",
        "AsyncMigration",
        "AsyncMigrationError",
        "InsightCachingState",
        "InstanceSetting",
        "Schedule",
        # --- Accessed via parent FK (no direct team-scoped lookup needed) ---
        "AlertSubscription",
        "Approval",
        "ApprovalRequest",
        "BatchExportLogEntry",
        "BatchExportRun",
        "EndpointVersion",
        "ErrorTrackingIssueAssignment",
        "TicketAssignment",
        # --- Internal config / OneToOne settings ---
        "DuckLakeCatalog",
        "EvaluationConfig",
        "RemoteConfig",
        "TeamCustomerAnalyticsConfig",
        "TeamDefaultEvaluationTag",
        "TeamMarketingAnalyticsConfig",
        "TeamRevenueAnalyticsConfig",
        # --- User preferences with no IDOR risk (read own data only) ---
        "FeatureFlagOverride",
        "NotificationViewed",
        "SessionRecordingPlaylistViewed",
        "UserPromptState",
        # --- Deprecated / special ---
        "DataWarehouseViewLink",
        "ErrorTrackingGroup",
        "ExplicitTeamMembership",
        # --- Other internal (no user-facing lookup by ID) ---
        "AlertCheck",
        "CohortCalculationHistory",
        "ColumnConfiguration",
        "ErrorTrackingIssueFingerprint",
        "ExperimentTimeseriesRecalculation",
        "GroupUsageMetric",
        "HogFunctionInvocationLog",
        "HostDefinition",
        "MaterializedColumnSlot",
        "MessagingRecord",
        "OrganizationResourceAccess",
        "PreaggregationJob",
        "ProductIntent",
        "SCIMDirectory",
        "SCIMProvisionedUser",
        "SchemaPropertyGroup",
        "SessionRecordingComment",
        "SessionSummary",
        "SharePassword",
        "UserActivity",
        "UserGroup",
        "UserGroupMembership",
        "ResourceTransfer",
    }

    team_scoped: set[str] = set()
    org_scoped: set[str] = set()
    user_scoped: set[str] = set()

    for model in apps.get_models():
        model_name = model.__name__

        # Skip abstract models
        if model._meta.abstract:
            continue

        # Skip proxy models
        if model._meta.proxy:
            continue

        # Check for FK fields
        has_team_fk = False
        has_org_fk = False
        has_user_fk = False

        for field in model._meta.get_fields():
            if not isinstance(field, ForeignKey):
                continue

            related_model_name = field.related_model.__name__

            if related_model_name == "Team":
                has_team_fk = True
            elif related_model_name == "Organization":
                has_org_fk = True
            elif related_model_name == "User":
                has_user_fk = True

        # Categorize based on FK combinations
        # Team FK takes precedence (even if user FK also exists)
        # Include ALL models (excluded ones tracked separately)
        if has_team_fk:
            team_scoped.add(model_name)
        elif has_org_fk:
            org_scoped.add(model_name)
        elif has_user_fk:
            user_scoped.add(model_name)

    return (
        {
            "team_scoped": team_scoped,
            "org_scoped": org_scoped,
            "user_scoped": user_scoped,
        },
        EXCLUDED_MODELS,
    )


def parse_semgrep_models(yaml_path: Path) -> dict[str, set[str]]:
    """
    Parse the semgrep YAML file and extract model names from regex patterns.

    Returns dict matching the scope categories.
    """
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    # Map rule IDs to scope categories
    # Note: user+team scoped models are treated as team_scoped in semgrep
    rule_scope_map = {
        "idor-taint-user-input-to-model-get": "team_scoped",
        "idor-lookup-without-team": "team_scoped",
        "idor-taint-user-input-to-org-model": "org_scoped",
        "idor-lookup-without-org": "org_scoped",
        "idor-taint-user-input-to-user-model": "user_scoped",
        "idor-lookup-without-user": "user_scoped",
        # User+team models are treated as team_scoped for comparison
        "idor-taint-user-input-to-user-team-model": "team_scoped",
        "idor-lookup-without-user-and-team": "team_scoped",
    }

    result: dict[str, set[str]] = {
        "team_scoped": set(),
        "org_scoped": set(),
        "user_scoped": set(),
    }

    for rule in data.get("rules", []):
        rule_id = rule.get("id", "")
        scope = rule_scope_map.get(rule_id)

        if not scope:
            continue

        # Extract regex from rule - handle both taint and pattern rules
        regex_pattern = None

        # For taint rules, look in pattern-sinks
        if "pattern-sinks" in rule:
            for sink in rule["pattern-sinks"]:
                if "metavariable-regex" in sink:
                    regex_pattern = sink["metavariable-regex"].get("regex", "")
                    break
                # Handle patterns list with metavariable-regex inside
                for pattern_item in sink.get("patterns", []):
                    if "metavariable-regex" in pattern_item:
                        regex_pattern = pattern_item["metavariable-regex"].get("regex", "")
                        break

        # For non-taint rules, look in patterns list
        if not regex_pattern and "patterns" in rule:
            for pattern_item in rule["patterns"]:
                if "metavariable-regex" in pattern_item:
                    regex_pattern = pattern_item["metavariable-regex"].get("regex", "")
                    break

        if regex_pattern:
            # Extract model names from regex like (?x)(Model1|Model2|...)
            # Remove (?x) extended mode flag and whitespace
            clean_pattern = re.sub(r"\s+", "", regex_pattern)
            clean_pattern = clean_pattern.replace("(?x)", "")

            # Extract names from alternation group
            match = re.search(r"\(([^)]+)\)", clean_pattern)
            if match:
                models_str = match.group(1)
                models = [m.strip() for m in models_str.split("|") if m.strip()]
                result[scope].update(models)

    return result


def main() -> int:
    setup_django()

    # Get models from code
    code_models, excluded_models = get_scoped_models()

    # Get models from semgrep rules
    semgrep_path = Path(__file__).parent.parent.parent / ".semgrep/rules/idor-team-scoped-models.yaml"
    semgrep_models = parse_semgrep_models(semgrep_path)

    # Compare and report
    has_errors = False
    has_warnings = False

    scope_labels = {
        "team_scoped": "Team-scoped",
        "org_scoped": "Organization-scoped",
        "user_scoped": "User-scoped",
    }

    # Union of all code models across scopes for staleness checks.
    # A model is only stale if it doesn't exist in ANY scope (cross-scope
    # categorization differences between script and semgrep are fine).
    all_code_models = code_models["team_scoped"] | code_models["org_scoped"] | code_models["user_scoped"]

    print("=" * 60)
    print("IDOR Semgrep Rule Coverage Check")
    print("=" * 60)

    for scope, label in scope_labels.items():
        all_in_code = code_models[scope]
        semgrep_set = semgrep_models[scope]

        # Split into excluded vs needs-checking
        excluded_in_scope = all_in_code & excluded_models
        to_check = all_in_code - excluded_models

        missing = to_check - semgrep_set
        # Models in semgrep that don't exist in code at all (in any scope)
        stale = semgrep_set - all_code_models

        print(f"\n{label} models:")
        print(f"  In code: {len(all_in_code)} ({len(excluded_in_scope)} excluded)")
        print(f"  In semgrep: {len(semgrep_set)}")

        if missing:
            has_errors = True
            print(f"\n  ❌ ERROR: Models missing from semgrep rules:")
            for model in sorted(missing):
                print(f"     - {model}")

        if stale:
            has_warnings = True
            print(f"\n  ⚠️  WARNING: Models in semgrep but not found in code (may be stale):")
            for model in sorted(stale):
                print(f"     - {model}")

        if not missing and not stale:
            print("  ✅ All models covered")

    print("\n" + "=" * 60)

    if has_errors:
        print("\n❌ FAILED: Some models are missing from semgrep IDOR rules.")
        print("\nTo fix:")
        print("  1. Add the missing models to .semgrep/rules/idor-team-scoped-models.yaml")
        print("  2. Or add them to EXCLUDED_MODELS in this script if they don't need IDOR protection")
        return 1

    if has_warnings:
        print("\n⚠️  PASSED with warnings: Some models in semgrep may be stale.")

    print("\n✅ All scoped models are covered by semgrep IDOR rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
