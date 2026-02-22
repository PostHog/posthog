from pathlib import Path

import pytest

from posthog.management.migration_squashing.planner import OperationBlocker
from posthog.management.migration_squashing.policy import BootstrapPolicy, write_bootstrap_policy_template


def test_bootstrap_policy_unresolved_action_remains_unresolved():
    policy = BootstrapPolicy.from_data(
        {
            "version": 1,
            "entries": [
                {
                    "app": "posthog",
                    "migration": "0401_example",
                    "operation_index": 1,
                    "nested_path": None,
                    "action": None,
                    "fingerprint": "sha256:test",
                }
            ],
        }
    )

    resolution = policy.resolve(
        app_label="posthog",
        migration="0401_example",
        operation_index=1,
        nested_path=None,
        fingerprint="sha256:test",
    )

    assert resolution is None


def test_bootstrap_policy_fingerprint_mismatch_fails_loudly():
    policy = BootstrapPolicy.from_data(
        {
            "version": 1,
            "entries": [
                {
                    "app": "posthog",
                    "migration": "0401_example",
                    "operation_index": 1,
                    "nested_path": "database_operations[0]",
                    "action": "keep",
                    "fingerprint": "sha256:expected",
                }
            ],
        }
    )

    with pytest.raises(ValueError):
        policy.resolve(
            app_label="posthog",
            migration="0401_example",
            operation_index=1,
            nested_path="database_operations[0]",
            fingerprint="sha256:actual",
        )


def test_bootstrap_policy_noop_if_empty_requires_tables():
    with pytest.raises(ValueError):
        BootstrapPolicy.from_data(
            {
                "version": 1,
                "entries": [
                    {
                        "app": "posthog",
                        "migration": "0401_example",
                        "operation_index": 1,
                        "action": "noop_if_empty",
                    }
                ],
            }
        )


def test_bootstrap_policy_noop_if_empty_resolves_with_tables():
    policy = BootstrapPolicy.from_data(
        {
            "version": 1,
            "entries": [
                {
                    "app": "posthog",
                    "migration": "0401_example",
                    "operation_index": 1,
                    "action": "noop_if_empty",
                    "tables": ["posthog_person", "public.posthog_event"],
                }
            ],
        }
    )

    resolution = policy.resolve(
        app_label="posthog",
        migration="0401_example",
        operation_index=1,
        nested_path=None,
        fingerprint="sha256:missing-is-allowed",
    )

    assert resolution is not None
    assert resolution.action == "noop_if_empty"
    assert resolution.tables == ("posthog_person", "public.posthog_event")


def test_write_bootstrap_policy_template_preserves_existing_actions(tmp_path: Path):
    path = tmp_path / "bootstrap_policy.yaml"
    path.write_text(
        """version: 1
entries:
  - app: posthog
    migration: 0401_example
    operation_index: 1
    action: keep
    fingerprint: sha256:existing
"""
    )

    write_bootstrap_policy_template(
        path=path,
        app_label="posthog",
        blockers=[
            OperationBlocker(
                migration="0401_example",
                operation_index=1,
                operation_type="RunPython",
                reason="Opaque operation type requires manual review before squashing.",
                fingerprint="sha256:new",
            ),
            OperationBlocker(
                migration="0402_example",
                operation_index=1,
                operation_type="RunSQL",
                reason="Opaque operation type requires manual review before squashing.",
                fingerprint="sha256:new2",
            ),
        ],
    )

    reloaded = BootstrapPolicy.from_path(path)
    assert reloaded.resolve(
        app_label="posthog",
        migration="0401_example",
        operation_index=1,
        nested_path=None,
        fingerprint="sha256:existing",
    )
    assert (
        reloaded.resolve(
            app_label="posthog",
            migration="0402_example",
            operation_index=1,
            nested_path=None,
            fingerprint="sha256:new2",
        )
        is None
    )
