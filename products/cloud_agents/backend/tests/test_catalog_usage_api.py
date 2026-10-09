from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.cloud_agents.backend.models import CloudAgentPreset, TeamCloudAgentsConfig
from products.cloud_agents.backend.tests.base import LOGIC, CloudAgentsFlagMixin, TasksFakeMixin, billing_dto
from products.tasks.backend.facade.pricing import get_cloud_agents_rate_card

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


class TestCatalogAndEstimate(TasksFakeMixin, CloudAgentsFlagMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("subscription_storage_on", True, ["auto", "own_subscription", "posthog"]),
            ("subscription_storage_off", False, ["auto", "posthog"]),
        ]
    )
    def test_catalog_prices_come_from_the_rate_card(
        self, _name: str, subscription_storage: bool, inference_modes: list[str]
    ) -> None:
        with team_scope(self.team.id):
            TeamCloudAgentsConfig.objects.create(team=self.team, max_concurrent_runs=12)
        rate_card = get_cloud_agents_rate_card()

        with patch(f"{LOGIC}.catalog.posthog_feature_flag_enabled", return_value=subscription_storage):
            body = self.client.get(f"{self.base_url()}/catalog/").json()

        assert body["rates"] == {
            "vcpu_hour_usd": _plain(rate_card.vcpu_hour_usd),
            "memory_gib_hour_usd": _plain(rate_card.memory_gib_hour_usd),
            "version": rate_card.version,
        }
        sizes = {size["name"]: size for size in body["sizes"]}
        assert list(sizes) == ["1x2", "2x4", "2x8", "4x8", "4x16", "8x16", "8x32", "16x64"]
        assert sizes["4x16"] == {"name": "4x16", "vcpu": 4, "memory_gib": 16, "price_per_hour_usd": "0.368"}
        for size in sizes.values():
            expected = size["vcpu"] * rate_card.vcpu_hour_usd + size["memory_gib"] * rate_card.memory_gib_hour_usd
            assert Decimal(size["price_per_hour_usd"]) == expected
        assert body["inference_modes"] == inference_modes
        assert body["limits"] == {"max_concurrent_runs": 12, "create_rate_per_hour": 60}
        assert [model["id"] for model in body["models"] if model["is_default"]] != []
        assert all(set(model) == {"id", "name", "runtime_adapter", "is_default"} for model in body["models"])

    def test_default_model_of_the_catalog_starts_a_run(self) -> None:
        catalog = self.client.get(f"{self.base_url()}/catalog/").json()
        (default_model,) = [model["id"] for model in catalog["models"] if model["is_default"]]

        response = self.client.post(
            f"{self.base_url()}/runs/", data={"prompt": "Fix it", "repositories": [{"name": "acme/app"}]}, format="json"
        )

        assert response.json()["config"]["model"] == default_model

    @parameterized.expand(
        [
            ("quarter_hour", "size=4x16&minutes=15", "0.368", "0.0920"),
            ("one_minute_rounds_to_four_places", "size=1x2&minutes=1", "0.066", "0.0011"),
        ]
    )
    def test_estimate(self, _name: str, query: str, price_per_hour: str, estimate: str) -> None:
        response = self.client.get(f"{self.base_url()}/estimate/?{query}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["price_per_hour_usd"], response.json()["estimate_usd"]) == (price_per_hour, estimate)

    @parameterized.expand([("no_size", "minutes=15", "size"), ("zero_minutes", "size=4x16&minutes=0", "minutes")])
    def test_estimate_needs_a_size_and_minutes(self, _name: str, query: str, attr: str) -> None:
        response = self.client.get(f"{self.base_url()}/estimate/?{query}")
        assert (response.status_code, response.json()["attr"]) == (status.HTTP_400_BAD_REQUEST, attr)


class TestUsageSummary(TasksFakeMixin, CloudAgentsFlagMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.preset = CloudAgentPreset.objects.create(team=self.team, name="Backend")
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other team")
        costs: list[tuple[datetime, dict[str, Any], dict[str, Any]]] = [
            (
                NOW - timedelta(days=2),
                {"compute_cost_cents": 150, "inference_cost_cents": 200},
                {"preset": self.preset},
            ),
            # The customer pays the model provider for this run, so its inference cost is not in the totals.
            (
                NOW - timedelta(days=2),
                {"compute_cost_cents": 25, "inference_cost_cents": 900, "inference_billing": "own_subscription"},
                {},
            ),
            (
                NOW - timedelta(days=1),
                {"compute_cost_cents": 100, "inference_cost_cents": 50},
                {"preset": self.preset},
            ),
            (NOW - timedelta(days=1), {}, {}),
            (NOW - timedelta(days=40), {"compute_cost_cents": 900}, {}),
            (NOW - timedelta(days=1), {"compute_cost_cents": 700}, {"team": other_team}),
        ]
        for created_at, billing, values in costs:
            with time_machine.travel(created_at, tick=False):
                self.make_run(
                    billing=billing_dto(vcpu_seconds=Decimal("100"), gib_seconds=Decimal("400"), **billing), **values
                )

    def usage(self, query: str = "") -> Any:
        with time_machine.travel(NOW, tick=False):
            return self.client.get(f"{self.base_url()}/usage/{query}")

    def test_usage_by_day_covers_the_last_thirty_days(self) -> None:
        body = self.usage().json()

        assert (body["date_from"], body["date_to"]) == ("2026-09-07T12:00:00Z", "2026-10-07T12:00:00Z")
        assert body["totals"] == {
            "runs": 4,
            "compute_usd": "2.7500",
            "inference_usd": "2.5000",
            "total_usd": "5.2500",
            "vcpu_seconds": "400.000",
            "gib_seconds": "1600.000",
        }
        assert [
            (bucket["key"], bucket["usage"]["runs"], bucket["usage"]["total_usd"]) for bucket in body["buckets"]
        ] == [
            ("2026-10-05", 2, "3.7500"),
            ("2026-10-06", 2, "1.5000"),
        ]

    def test_usage_by_preset(self) -> None:
        body = self.usage("?group_by=preset").json()

        assert body["group_by"] == "preset"
        assert [
            (bucket["key"], bucket["name"], bucket["usage"]["runs"], bucket["usage"]["total_usd"])
            for bucket in body["buckets"]
        ] == [(str(self.preset.id), "Backend", 2, "5.0000"), (None, None, 2, "0.2500")]

    def test_usage_in_a_date_range(self) -> None:
        body = self.usage("?date_from=2026-08-01T00:00:00Z&date_to=2026-09-01T00:00:00Z").json()
        assert (body["totals"]["runs"], body["totals"]["compute_usd"]) == (1, "9.0000")

    @parameterized.expand(
        [
            ("end_before_start", "?date_from=2026-10-02T00:00:00Z&date_to=2026-10-01T00:00:00Z"),
            ("range_too_long", "?date_from=2024-01-01T00:00:00Z"),
        ]
    )
    def test_invalid_range(self, _name: str, query: str) -> None:
        response = self.usage(query)
        assert (response.status_code, response.json()["attr"]) == (status.HTTP_400_BAD_REQUEST, "date_from")
