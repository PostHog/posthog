from datetime import datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.test.persons import create_person

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.actions.backend.models.action import Action
from products.customer_analytics.backend.facade.api import get_key_metrics, get_key_metrics_fingerprint


class TestKeyMetrics(ClickhouseTestMixin, BaseTest):
    def _midnight(self) -> datetime:
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    @parameterized.expand(
        [
            ("an unrestricted viewer", False, [], {"signup_event": (7.0, 7.0), "activity_event": (2.0, 1.0)}),
            (
                "a viewer who cannot read the browser",
                True,
                [],
                {"signup_event": (0.0, 0.0), "activity_event": (2.0, 1.0)},
            ),
            (
                "a project that marks Chrome as a test account",
                False,
                [{"key": "$browser", "value": "Chrome", "operator": "is_not", "type": "event"}],
                {"signup_event": (0.0, 0.0), "activity_event": (1.0, 0.0)},
            ),
        ]
    )
    def test_key_metrics_count_filtered_events_and_weekly_unique_people(
        self,
        _name: str,
        restricted: bool,
        test_account_filters: list[dict[str, str]],
        expected: dict[str, tuple[float, float]],
    ) -> None:
        self.team.test_account_filters = test_account_filters
        self.team.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        viewer = self._create_user("viewer@example.com")
        if restricted:
            definition = PropertyDefinition.objects.create(
                team=self.team, name="$browser", type=PropertyDefinition.Type.EVENT
            )
            upsert_property_access_control(
                team_id=self.team.id,
                created_by_id=None,
                input=UpsertPropertyAccessControlInput(
                    access_level=PropertyAccessLevel.NONE,
                    property_definition_id=str(definition.id),
                    organization_member_id=viewer.organization_memberships.get().id,
                ),
            )
        config = self.team.customer_analytics_config
        config.signup_event = {
            "kind": "EventsNode",
            "event": None,
            "properties": [{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}],
        }
        config.activity_event = {"kind": "EventsNode", "event": "opened_file"}
        config.payment_event = {"kind": "ActionsNode", "id": 999_999}
        config.save()
        for browser, days in (("Chrome", 20), ("Firefox", 7)):
            create_person(team=self.team, distinct_ids=[f"person-{browser}"])
            for day in range(1, days + 1):
                _create_event(
                    team=self.team,
                    event="opened_file",
                    distinct_id=f"person-{browser}",
                    properties={"$browser": browser},
                    timestamp=self._midnight() - timedelta(days=day) + timedelta(hours=12),
                )
        flush_persons_and_events()

        metrics = get_key_metrics(team=self.team, user=viewer)

        self.assertEqual(
            ({m.key: (m.this_week, m.last_week) for m in metrics}, {m.key: len(m.daily) for m in metrics}),
            (expected, {"signup_event": 35, "activity_event": 35}),
        )

    def test_the_fingerprint_changes_only_when_an_action_or_the_test_account_filters_change(self) -> None:
        with time_machine.travel("2026-03-02T09:00:00Z", tick=False) as traveller:
            action = Action.objects.create(
                team=self.team,
                name="Paid",
                steps_json=[
                    {
                        "event": "paid",
                        "properties": [
                            {"key": "plan_started", "value": "-7d", "operator": "is_date_after", "type": "event"}
                        ],
                    }
                ],
            )
            config = self.team.customer_analytics_config
            config.payment_event = {"kind": "ActionsNode", "id": action.id}
            config.save()
            prints = [get_key_metrics_fingerprint(self.team)]
            traveller.shift(timedelta(hours=1))
            prints.append(get_key_metrics_fingerprint(self.team))
            action.steps_json = [{"event": "checkout completed"}]
            action.save()
            prints.append(get_key_metrics_fingerprint(self.team))
            action.deleted = True
            action.save()
            prints.append(get_key_metrics_fingerprint(self.team))
            self.team.test_account_filters = [
                {"key": "email", "value": "@example.com", "operator": "not_icontains", "type": "person"}
            ]
            self.team.save()
            prints.append(get_key_metrics_fingerprint(self.team))

        self.assertEqual((prints[0], len(set(prints[1:]))), (prints[1], 4))
