import dataclasses
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.workload_identity.providers import WorkloadClaim
from posthog.workload_identity.test.fixtures import FAKE_WORKLOAD_PROVIDER


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
            ("subject_as_condition_claim", {"condition_claims": (WorkloadClaim(name="repository_id", label="ID"),)}),
        ]
    )
    def test_rejects_an_entry_the_exchange_or_activity_log_cannot_use(
        self, _name: str, overrides: dict[str, Any]
    ) -> None:
        with self.assertRaises(ValueError):
            dataclasses.replace(FAKE_WORKLOAD_PROVIDER, **overrides)
