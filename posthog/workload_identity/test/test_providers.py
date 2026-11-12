import dataclasses
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.workload_identity.providers import (
    DEPOT_CI,
    GITHUB_ACTIONS,
    GITLAB,
    ConditionPreset,
    WorkloadClaim,
    WorkloadProvider,
)
from posthog.workload_identity.test.fixtures import FAKE_WORKLOAD_PROVIDER
from posthog.workload_identity.trust_policy import validate_condition_companions


class TestWorkloadProviderEntry(SimpleTestCase):
    @parameterized.expand(
        [
            ("template_field_not_recorded", {"actor_label_template": "{repository} · {job}"}),
            ("positional_template_field", {"run_url_template": "https://ci.example.com/{}"}),
            ("attribute_template_field", {"run_url_template": "https://ci.example.com/{repository.name}"}),
            (
                "duplicate_condition_claim",
                {"condition_claims": (WorkloadClaim(name="ref", label="Ref"), WorkloadClaim(name="ref", label="Ref"))},
            ),
            ("required_claim_policies_cannot_set", {"required_condition_claims": ("sha",)}),
            ("subject_as_condition_claim", {"condition_claims": (WorkloadClaim(name="repository_id", label="ID"),)}),
            (
                "preset_on_a_claim_policies_cannot_set",
                {
                    "condition_presets": (
                        ConditionPreset(key="x", label="X", help_text="", conditions=(("sha", "abc"),)),
                    )
                },
            ),
            (
                "preset_with_two_values_in_one_claim",
                {
                    "condition_presets": (
                        ConditionPreset(key="x", label="X", help_text="", conditions=(("ref", "{value}/{value}"),)),
                    )
                },
            ),
        ]
    )
    def test_rejects_an_entry_the_exchange_or_activity_log_cannot_use(
        self, _name: str, overrides: dict[str, Any]
    ) -> None:
        with self.assertRaises(ValueError):
            dataclasses.replace(FAKE_WORKLOAD_PROVIDER, **overrides)

    @parameterized.expand(
        [
            ("no_required_claims", GITHUB_ACTIONS, (), ("branch_push",)),
            ("required_claims", DEPOT_CI, ("organization",), ("organization", "branch_push")),
        ]
    )
    def test_marks_the_presets_a_new_policy_needs_and_starts_with(
        self, _name: str, provider: WorkloadProvider, required: tuple[str, ...], default: tuple[str, ...]
    ) -> None:
        assert provider.required_presets == required
        assert provider.default_presets == default


class TestRegistryConditionCompanions(SimpleTestCase):
    @parameterized.expand(
        [
            ("github_ref_alone", GITHUB_ACTIONS, {"ref": "refs/heads/main"}, False),
            (
                "github_workflow_alone",
                GITHUB_ACTIONS,
                {"workflow_ref": "acme/web/.github/workflows/ci.yml@refs/heads/main"},
                False,
            ),
            ("github_branch_push", GITHUB_ACTIONS, {"ref": "refs/heads/main", "event_name": "push"}, True),
            (
                "github_ref_and_environment",
                GITHUB_ACTIONS,
                {"ref": "refs/heads/main", "environment": "production"},
                True,
            ),
            ("gitlab_ref_alone", GITLAB, {"ref": "main", "ref_protected": "true"}, False),
            ("gitlab_protected_branch", GITLAB, {"ref": "main", "ref_type": "branch", "ref_protected": "true"}, True),
            ("gitlab_environment_alone", GITLAB, {"environment": "production", "environment_protected": "true"}, False),
            ("depot_ref_alone", DEPOT_CI, {"org_id": "o", "forge": "github", "ref": "refs/heads/main"}, False),
            (
                "depot_branch_push",
                DEPOT_CI,
                {"org_id": "o", "forge": "github", "ref": "refs/heads/main", "event_name": "push"},
                True,
            ),
        ]
    )
    def test_a_provider_refuses_claims_that_trust_fork_runs_on_their_own(
        self, _name: str, provider: WorkloadProvider, conditions: dict[str, str], allowed: bool
    ) -> None:
        if allowed:
            validate_condition_companions(conditions, provider)
        else:
            with self.assertRaises(ValidationError):
                validate_condition_companions(conditions, provider)
