import copy
import datetime
from typing import Any, cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.billing.entitlements import apply_entitlements
from posthog.billing.entitlements_contract import load_contract
from posthog.redis import get_client

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingStatus
from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource
from ee.models.license import License, LicenseManager

PERIOD = ["2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"]


def _block(**overrides: Any) -> dict[str, Any]:
    contract = load_contract()
    block: dict[str, Any] = {
        "schema_version": 1,
        "contract_hash": contract["contract_hash"],
        "plan_state": "free",
        "usage_limits": dict.fromkeys(contract["usage_keys"]),
        "trust_scores": dict.fromkeys(contract["usage_keys"], 0),
        "never_drop_data": False,
        "features": [{"key": "basic", "name": "Basic"}],
    }
    for key, value in overrides.items():
        if key in ("usage_limits", "trust_scores"):
            block[key] = {**block[key], **value}
        else:
            block[key] = value
    return block


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


class TestApplyEntitlements(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.usage = {
            "events": {"usage": 90, "limit": 1000, "todays_usage": 10},
            "rows_exported": {"usage": 5, "limit": None, "todays_usage": 0},
            "api_queries_read_bytes": {"usage": 1, "limit": 77, "todays_usage": 0},
            "signals_spend_credits": {},
            "period": PERIOD,
        }
        self.organization.customer_trust_scores = {"events": 15}
        self.organization.never_drop_data = True
        self.organization.available_product_features = [{"key": "paid_feature", "name": "Paid"}]
        self.organization.save()

    def test_replaces_every_entitlement_field(self) -> None:
        block = _block(
            usage_limits={"events": 1_000_000, "rows_exported": 1_000_000, "signals_spend_credits": 5},
            trust_scores={"events": 0},
        )

        changed = apply_entitlements(self.organization, block)

        assert changed == frozenset({"usage_limits", "trust_scores", "never_drop_data", "features"})
        assert self.organization.customer_trust_scores == block["trust_scores"]
        assert self.organization.never_drop_data is False
        assert self.organization.available_product_features == [{"key": "basic", "name": "Basic"}]
        usage = cast(dict[str, Any], self.organization.usage)
        assert usage["events"] == {"usage": 90, "limit": 1_000_000, "todays_usage": 10}
        assert usage["rows_exported"]["limit"] == 1_000_000
        assert usage["api_queries_read_bytes"]["limit"] == 77
        assert usage["signals_spend_credits"] == {}

    def test_applies_an_empty_feature_list(self) -> None:
        apply_entitlements(self.organization, _block(features=[]))

        assert self.organization.available_product_features == []

    def test_reports_no_change_when_the_snapshot_matches(self) -> None:
        block = _block(
            usage_limits={"events": 1000},
            trust_scores={"events": 15},
            never_drop_data=True,
            features=[{"key": "paid_feature", "name": "Paid"}],
        )
        apply_entitlements(self.organization, block)

        assert apply_entitlements(self.organization, block) == frozenset()

    def test_a_false_never_drop_data_does_not_rewrite_an_unset_one(self) -> None:
        self.organization.never_drop_data = None

        changed = apply_entitlements(self.organization, _block(never_drop_data=False))

        assert changed is not None and "never_drop_data" not in changed
        assert self.organization.never_drop_data is None

    @parameterized.expand(
        [
            ("unsupported_schema_version", lambda b: b.update(schema_version=2)),
            ("malformed", lambda b: b["usage_limits"].update(events=-1)),
            ("malformed", lambda b: b.update(usage_limits=["events"])),
            ("malformed", lambda b: b.update(features=None)),
            ("malformed", lambda b: b["trust_scores"].update(events="high")),
            ("malformed", lambda b: b.pop("never_drop_data")),
        ]
    )
    def test_rejects_a_snapshot_and_keeps_the_previous_state(self, reason: str, break_block: Any) -> None:
        block = _block(usage_limits={"events": 1})
        break_block(block)
        before = copy.deepcopy(
            (
                self.organization.usage,
                self.organization.customer_trust_scores,
                self.organization.never_drop_data,
                self.organization.available_product_features,
            )
        )
        rejected_before = _sample("billing_snapshot_rejected_total", {"reason": reason})

        assert apply_entitlements(self.organization, block) is None

        after = (
            self.organization.usage,
            self.organization.customer_trust_scores,
            self.organization.never_drop_data,
            self.organization.available_product_features,
        )
        assert after == before
        assert _sample("billing_snapshot_rejected_total", {"reason": reason}) == rejected_before + 1

    def test_a_billed_key_the_snapshot_leaves_out_keeps_its_limit_and_the_rest_applies(self) -> None:
        block = _block(usage_limits={"rows_exported": 7}, trust_scores={"events": 3})
        del block["usage_limits"]["events"]
        missing_before = _sample("billing_snapshot_missing_usage_limit_total", {"usage_key": "events"})

        changed = apply_entitlements(self.organization, block)

        usage = cast(dict[str, Any], self.organization.usage)
        assert changed is not None and "usage_limits" in changed
        assert usage["events"]["limit"] == 1000
        assert usage["rows_exported"]["limit"] == 7
        assert self.organization.customer_trust_scores == block["trust_scores"]
        assert _sample("billing_snapshot_missing_usage_limit_total", {"usage_key": "events"}) == missing_before + 1

    def test_counts_a_billed_limit_with_no_usage_entry_to_store_it_in(self) -> None:
        labels = {"usage_key": "signals_spend_credits"}
        before = _sample("billing_entitlement_limit_skipped_total", labels)

        apply_entitlements(self.organization, _block(usage_limits={"signals_spend_credits": 5, "mobile_recordings": 9}))

        assert cast(dict[str, Any], self.organization.usage)["signals_spend_credits"] == {}
        assert _sample("billing_entitlement_limit_skipped_total", labels) == before + 1
        assert _sample("billing_entitlement_limit_skipped_total", {"usage_key": "mobile_recordings"}) == 0

    def test_a_different_contract_hash_marks_the_contract_stale_and_still_applies(self) -> None:
        apply_entitlements(self.organization, _block(contract_hash="something-else", trust_scores={"events": 3}))

        assert _sample("billing_contract_stale") == 1
        assert self.organization.customer_trust_scores is not None
        assert self.organization.customer_trust_scores["events"] == 3

        apply_entitlements(self.organization, _block())

        assert _sample("billing_contract_stale") == 0

    @parameterized.expand([("batch", 1), ("on_demand", 0), (None, 0)])
    def test_counts_drift_only_when_a_batch_sync_changes_a_field(self, sync_type: str | None, expected: int) -> None:
        before = {
            field: _sample("billing_entitlement_drift_repaired_total", {"field": field, "plan_state": "free"})
            for field in ("trust_scores", "features")
        }

        apply_entitlements(
            self.organization,
            _block(
                usage_limits={"events": 1000}, never_drop_data=True, features=[{"key": "paid_feature", "name": "Paid"}]
            ),
            sync_type=sync_type,
        )

        assert _sample("billing_entitlement_drift_repaired_total", {"field": "trust_scores", "plan_state": "free"}) == (
            before["trust_scores"] + expected
        )
        assert (
            _sample("billing_entitlement_drift_repaired_total", {"field": "features", "plan_state": "free"})
            == before["features"]
        )

    def _matching_block(self, **overrides: Any) -> dict[str, Any]:
        return _block(
            usage_limits={"events": 1000},
            never_drop_data=True,
            features=[{"key": "paid_feature", "name": "Paid"}],
            **overrides,
        )

    def test_gaining_zero_valued_trust_score_keys_is_written_but_not_counted_as_drift(self) -> None:
        labels = {"field": "trust_scores", "plan_state": "free"}
        before = _sample("billing_entitlement_drift_repaired_total", labels)
        block = self._matching_block(trust_scores={"events": 15})

        changed = apply_entitlements(self.organization, block, sync_type="batch")

        assert changed == frozenset({"trust_scores"})
        assert self.organization.customer_trust_scores == block["trust_scores"]
        assert _sample("billing_entitlement_drift_repaired_total", labels) == before

    @parameterized.expand(
        [
            ("changed_score", {"events": 15}, {"events": 3}),
            ("missing_stored_key_against_a_nonzero_score", {"events": 15}, {"events": 15, "recordings": 5}),
            ("nonzero_stored_key_the_snapshot_drops", {"events": 15, "legacy_key": 4}, {"events": 15}),
        ]
    )
    def test_a_real_trust_score_difference_counts_as_drift(
        self, _name: str, stored: dict[str, int], snapshot_scores: dict[str, int]
    ) -> None:
        self.organization.customer_trust_scores = stored
        labels = {"field": "trust_scores", "plan_state": "free"}
        before = _sample("billing_entitlement_drift_repaired_total", labels)
        block = self._matching_block(trust_scores=snapshot_scores)

        apply_entitlements(self.organization, block, sync_type="batch")

        assert self.organization.customer_trust_scores == block["trust_scores"]
        assert _sample("billing_entitlement_drift_repaired_total", labels) == before + 1


class TestUpdateOrgDetailsWithEntitlements(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        self.organization.usage = {
            "events": {"usage": 10, "limit": 1000, "todays_usage": 0},
            "workflow_destinations": {"usage": 1, "limit": 500, "todays_usage": 0},
            "period": PERIOD,
        }
        self.organization.customer_trust_scores = {"events": 15}
        self.organization.never_drop_data = True
        self.organization.available_product_features = [{"key": "paid_feature", "name": "Paid"}]
        self.organization.save()

    def _status(self, **customer: Any) -> BillingStatus:
        return cast(
            BillingStatus,
            {
                "customer": {
                    "usage_summary": {
                        "events": {"usage": 20, "limit": 999},
                        "recordings": {},
                        "workflow_destinations": {"usage": 2, "limit": 999},
                    },
                    "billing_period": {"current_period_start": PERIOD[0], "current_period_end": PERIOD[1]},
                    "available_product_features": [{"key": "legacy_feature", "name": "Legacy"}],
                    "never_drop_data": True,
                    "customer_trust_scores": {"product_analytics": 10},
                    "products": [{"type": "product_analytics", "usage_key": "events"}],
                    **customer,
                }
            },
        )

    @patch("ee.billing.billing_manager.update_org_billing_quotas")
    def test_the_block_decides_entitlements_and_the_summary_keeps_usage(self, _update_quotas: Any) -> None:
        block = _block(usage_limits={"events": 5000, "workflow_destinations": 100})

        BillingManager(self.license).update_org_details(self.organization, self._status(entitlements=block))

        self.organization.refresh_from_db()
        usage = cast(dict[str, Any], self.organization.usage)
        assert usage["events"]["usage"] == 20
        assert usage["events"]["limit"] == 5000
        assert usage["workflow_destinations"] == {"usage": 2, "limit": 100, "todays_usage": 0}
        assert self.organization.customer_trust_scores == block["trust_scores"]
        assert self.organization.never_drop_data is False
        assert self.organization.available_product_features == [{"key": "basic", "name": "Basic"}]

    @time_machine.travel("2024-01-15T12:00:00Z", tick=False)
    def test_a_lowered_limit_from_the_block_limits_workflow_destinations(self) -> None:
        block = _block(usage_limits={"workflow_destinations": 1})

        with patch("posthoganalytics.feature_enabled", return_value=False):
            BillingManager(self.license).update_org_details(self.organization, self._status(entitlements=block))

        self.organization.refresh_from_db()
        usage = cast(dict[str, Any], self.organization.usage)
        assert usage["workflow_destinations"]["quota_limited_until"] is not None
        assert (
            get_client().zscore(
                f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}workflow_destinations", self.team.api_token
            )
            is not None
        )

    @parameterized.expand(
        [
            ("rejected_block", {"entitlements": {**_block(), "schema_version": 2}}, False),
            ("missing_block_when_required", {}, True),
        ]
    )
    @patch("ee.billing.billing_manager.update_org_billing_quotas")
    def test_keeps_the_previous_entitlements(
        self, _name: str, customer: dict[str, Any], require_block: bool, _update_quotas: Any
    ) -> None:
        with override_settings(BILLING_REQUIRE_ENTITLEMENTS_BLOCK=require_block):
            BillingManager(self.license).update_org_details(self.organization, self._status(**customer))

        self.organization.refresh_from_db()
        usage = cast(dict[str, Any], self.organization.usage)
        assert usage["events"]["usage"] == 20
        assert usage["events"]["limit"] == 1000
        assert usage["workflow_destinations"]["limit"] == 500
        assert self.organization.customer_trust_scores == {"events": 15}
        assert self.organization.never_drop_data is True
        assert self.organization.available_product_features == [{"key": "paid_feature", "name": "Paid"}]

    @patch("ee.billing.billing_manager.update_org_billing_quotas")
    def test_without_a_block_the_legacy_fields_apply(self, _update_quotas: Any) -> None:
        BillingManager(self.license).update_org_details(self.organization, self._status())

        self.organization.refresh_from_db()
        usage = cast(dict[str, Any], self.organization.usage)
        assert usage["events"]["limit"] == 999
        assert usage["workflow_destinations"]["limit"] == 999
        assert self.organization.customer_trust_scores == {"events": 10}
        assert self.organization.available_product_features == [{"key": "legacy_feature", "name": "Legacy"}]

    @patch("ee.billing.billing_manager.update_org_billing_quotas")
    def test_a_batch_sync_counts_the_fields_it_repaired(self, _update_quotas: Any) -> None:
        labels = {"field": "features", "plan_state": "paid"}
        before = _sample("billing_entitlement_drift_repaired_total", labels)

        BillingManager(self.license).update_org_details(
            self.organization, self._status(entitlements=_block(plan_state="paid")), sync_type="batch"
        )

        assert _sample("billing_entitlement_drift_repaired_total", labels) == before + 1

    @patch("ee.billing.billing_manager.update_org_billing_quotas")
    def test_every_billed_quota_resource_gets_a_limit_from_the_block(self, _update_quotas: Any) -> None:
        billed = [resource.value for resource in QuotaResource if resource.billed]
        summary = {usage_key: {"usage": 1, "limit": 999} for usage_key in billed} | {"recordings": {"usage": 1}}
        block = _block(usage_limits=dict.fromkeys(billed, 50))

        BillingManager(self.license).update_org_details(
            self.organization, self._status(usage_summary=summary, entitlements=block)
        )

        self.organization.refresh_from_db()
        usage = cast(dict[str, Any], self.organization.usage)
        assert {usage_key: usage[usage_key]["limit"] for usage_key in billed} == dict.fromkeys(billed, 50)
