import uuid
import datetime as dt
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.data_warehouse.backend.temporal.health_checks.webhook_subscription_stale import (
    WebhookSubscriptionStaleCheck,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

SOURCE_MGMT = "products.warehouse_sources.backend.facade.source_management"

DESIRED_EVENTS = ["charge.succeeded", "customer.created", "invoice.paid"]


class _FakeWebhookBase:
    pass


class _FakeStripeSource(_FakeWebhookBase):
    def __init__(self, enabled_events: list[str] | None, exists: bool = True, error: str | None = None) -> None:
        self._enabled_events = enabled_events
        self._exists = exists
        self._error = error

    def parse_config(self, job_inputs: dict) -> dict:
        return job_inputs

    def resolve_api_version(self, pinned: str | None) -> str:
        return pinned or "2020-08-27"

    def webhook_mapping_key(self, schema_name: str) -> str:
        return schema_name

    def get_external_webhook_info(
        self, config: Any, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return ExternalWebhookInfo(exists=self._exists, enabled_events=self._enabled_events, error=self._error)

    def get_desired_webhook_events(self, config: Any, eligible_schema_names: list[str]) -> list[str]:
        return DESIRED_EVENTS


class TestWebhookSubscriptionStaleCheck(BaseTest):
    def _create_webhook_source(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            team=self.team,
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "sk_test_x"},
        )
        HogFunction.objects.create(
            team=self.team,
            type="warehouse_source_webhook",
            hog="return event",
            inputs_schema=[{"key": "source_id", "type": "string"}],
            inputs={"source_id": {"value": str(source.pk)}},
        )
        return source

    def _create_webhook_schema(
        self, source: ExternalDataSource, name: str, last_synced_at: dt.datetime | None
    ) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
            last_synced_at=last_synced_at,
        )

    def _detect(self, source_impl: _FakeStripeSource) -> list[dict]:
        registry = mock.Mock()
        registry.get_source.return_value = source_impl
        with (
            mock.patch(f"{SOURCE_MGMT}.SourceRegistry", registry),
            mock.patch(f"{SOURCE_MGMT}.WebhookSource", _FakeWebhookBase),
        ):
            issues = WebhookSubscriptionStaleCheck().detect([self.team.id])
        return [result.payload for result in issues.get(self.team.id, [])]

    @parameterized.expand(
        [
            ("own_events_unsubscribed", ["invoice.paid"], True),
            ("own_events_subscribed", ["charge.succeeded"], False),
            ("wildcard", ["*"], False),
        ]
    )
    def test_reports_only_when_a_schemas_own_events_are_missing(
        self, _name: str, enabled_events: list[str], flagged: bool
    ) -> None:
        source = self._create_webhook_source()
        self._create_webhook_schema(source, "charge", last_synced_at=None)

        payloads = self._detect(_FakeStripeSource(enabled_events))

        if flagged:
            assert len(payloads) == 1
            assert payloads[0]["pipeline_id"] == str(source.pk)
            assert payloads[0]["missing_events"] == ["charge.succeeded"]
            assert payloads[0]["affected_schemas"] == ["charge"]
        else:
            assert payloads == []

    def test_only_flags_schemas_whose_own_events_are_unsubscribed(self) -> None:
        source = self._create_webhook_source()
        self._create_webhook_schema(source, "charge", last_synced_at=None)
        self._create_webhook_schema(source, "customer", last_synced_at=None)

        payloads = self._detect(_FakeStripeSource(["charge.succeeded"]))

        assert len(payloads) == 1
        assert payloads[0]["affected_schemas"] == ["customer"]
        assert payloads[0]["missing_events"] == ["customer.created"]

    def test_schema_that_has_ever_synced_is_not_a_candidate(self) -> None:
        source = self._create_webhook_source()
        self._create_webhook_schema(source, "charge", last_synced_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))

        assert self._detect(_FakeStripeSource(["invoice.paid"])) == []

    def test_unreadable_endpoint_is_skipped(self) -> None:
        source = self._create_webhook_source()
        self._create_webhook_schema(source, "charge", last_synced_at=None)

        assert self._detect(_FakeStripeSource(None, exists=False, error="cannot read webhook endpoint")) == []
