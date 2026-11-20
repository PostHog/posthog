from typing import cast

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.billing.entitlements_contract import (
    BillingContractMismatch,
    EntitlementsContract,
    check_billed_resources,
    load_contract,
    posthog_enforced_usage_keys,
)

from ee.billing.quota_limiting import QuotaResource


def _contract(usage_keys: dict[str, str]) -> EntitlementsContract:
    return cast(
        EntitlementsContract,
        {
            "schema_version": 1,
            "contract_hash": "hash",
            "limited_features": {},
            "usage_keys": {
                key: {"quota_enforcement": enforcement, "quota_enforcement_note": None, "products": []}
                for key, enforcement in usage_keys.items()
            },
        },
    )


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestEntitlementsContract(SimpleTestCase):
    def test_billed_quota_resources_are_the_contracts_posthog_enforced_keys(self) -> None:
        contract = load_contract()
        known = {resource.value for resource in QuotaResource}

        billed = {resource.value for resource in QuotaResource if resource.billed}

        assert billed == posthog_enforced_usage_keys(contract) & known

    def test_workflow_destinations_is_read_under_billings_usage_key(self) -> None:
        assert QuotaResource.WORKFLOW_DESTINATIONS.value == "workflow_destinations"
        assert QuotaResource.WORKFLOW_DESTINATIONS.billed
        assert QuotaResource("workflow_destinations") is QuotaResource.WORKFLOW_DESTINATIONS

    @parameterized.expand(
        [
            ("billed_key_billing_does_not_send", {"events", "made_up"}, {"events", "made_up"}, {"events": "posthog"}),
            (
                "billing_enforced_key_not_billed",
                {"events"},
                {"events", "rows_exported"},
                {"events": "posthog", "rows_exported": "posthog"},
            ),
            (
                "billed_key_billing_does_not_enforce",
                {"events", "mobile_recordings"},
                {"events", "mobile_recordings"},
                {"events": "posthog", "mobile_recordings": "none"},
            ),
        ]
    )
    def test_a_mismatch_stops_the_process(
        self, _name: str, billed: set[str], known: set[str], usage_keys: dict[str, str]
    ) -> None:
        with self.assertRaises(BillingContractMismatch):
            check_billed_resources(billed=billed, known=known, contract=_contract(usage_keys))

    def test_contract_keys_posthog_does_not_know_are_reported_not_fatal(self) -> None:
        contract = _contract({"events": "posthog", "brand_new_key": "posthog", "unenforced_new_key": "none"})

        unknown = check_billed_resources(billed={"events"}, known={"events"}, contract=contract)

        assert unknown == frozenset({"brand_new_key"})
        assert _sample("billing_contract_unknown_usage_keys", {"usage_key": "brand_new_key"}) == 1
