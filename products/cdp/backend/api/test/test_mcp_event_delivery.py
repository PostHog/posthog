import json
import base64
from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue

if TYPE_CHECKING:
    pass

from rest_framework.exceptions import PermissionDenied

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.actions.backend.models.action import Action
from products.cdp.backend.api.test.mcp_event_test_utils import MCPEventServiceTestCase
from products.cdp.backend.mcp_events import MCPEventSubscriptions
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription
from products.cdp.backend.tasks.hog_functions import refresh_affected_hog_functions


class TestMCPEventDelivery(MCPEventServiceTestCase):
    @parameterized.expand(["event", "deleted_action"])
    def test_refresh_reuses_destination_and_unsubscribe_blocks_queued_delivery(self, source: str) -> None:
        action = None
        if source == "deleted_action":
            action = Action.objects.create(
                team=self.team, name="Example action", steps_json=[{"event": "example_event"}]
            )
            self.payload["arguments"] = {
                "project_id": self.team.pk,
                "filters": {"actions": [{"id": str(action.pk), "type": "actions"}]},
            }
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        first_function_id = subscription.hog_function_id
        first_generation = subscription.generation
        self.assertIn("mcpEventFetch(", subscription.hog_function.hog)
        verified_at = timezone.now() - timedelta(minutes=30)
        subscription.verified_at = verified_at
        subscription.save(update_fields=["verified_at"])
        self.assertNotIn(self.key, json.dumps(subscription.hog_function.inputs))
        self.assertEqual(subscription.hog_function.encrypted_inputs["mcp_credential"]["value"], self.key)
        self.assertNotIn("signing_secret", subscription.hog_function.encrypted_inputs)
        self.assertNotIn(self.secret, json.dumps(subscription.hog_function.inputs))
        self.assertNotIn(self.secret, json.dumps(subscription.hog_function.encrypted_inputs))
        refreshed = self.subscribe()
        self.assertEqual(refreshed.pk, subscription.pk)
        self.assertEqual(refreshed.hog_function_id, first_function_id)
        self.assertEqual(refreshed.generation, first_generation)
        self.assertEqual(refreshed.verified_at, verified_at)

        if action is not None:
            action.deleted = True
            action.save(update_fields=["deleted"])
        for _ in range(2):
            self.unsubscribe()
        subscription.refresh_from_db()
        subscription.hog_function.refresh_from_db()
        self.assertFalse(subscription.active)
        self.assertFalse(subscription.hog_function.enabled)
        with self.assertRaises(PermissionDenied):
            self.authorize(subscription, first_generation)

    def test_delivery_uses_event_id_and_refresh_rotates_signatures(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        response = self.authorize(subscription)
        result = response
        event_id = json.loads(result["body"])["eventId"]
        self.assertEqual(result["headers"]["webhook-id"], event_id)
        self.assertNotIn(self.secret, json.dumps(result))

        self.payload["delivery"] = {
            "mode": "webhook",
            "url": self.callback_url,
            "secret": "whsec_" + base64.b64encode(b"b" * 32).decode(),
        }
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        response = self.authorize(subscription)
        self.assertEqual(len(response["headers"]["webhook-signature"].split()), 2)

    def test_expired_subscription_and_stale_generation_cannot_deliver(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        subscription.expires_at = timezone.now() - timedelta(seconds=1)
        subscription.save(update_fields=["expires_at"])
        with self.assertRaises(PermissionDenied):
            self.authorize(subscription)
        old_generation = subscription.generation
        with (
            patch("products.cdp.backend.mcp_events.EXPIRY_BATCH_SIZE", 1),
            patch("products.cdp.backend.mcp_events.expire_mcp_event_subscriptions.delay") as continuation,
        ):
            self.assertEqual(MCPEventSubscriptions.expire(), 1)
            continuation.assert_called_once_with()
            self.assertEqual(MCPEventSubscriptions.expire(), 0)
            continuation.assert_called_once_with()
        subscription.refresh_from_db()
        subscription.hog_function.refresh_from_db()
        self.assertFalse(subscription.active)
        self.assertFalse(subscription.hog_function.enabled)
        refreshed = self.subscribe()
        self.assertNotEqual(refreshed.generation, old_generation)
        with self.assertRaises(PermissionDenied):
            self.authorize(refreshed, old_generation)

    @parameterized.expand(
        [
            (
                "event",
                PropertyDefinition.Type.EVENT,
                {"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"},
            ),
            (
                "person",
                PropertyDefinition.Type.PERSON,
                {"key": "plan", "type": "person", "operator": "exact", "value": "enterprise"},
            ),
            (
                "pdi_field",
                PropertyDefinition.Type.PERSON,
                {"type": "hogql", "key": "pdi.person.properties.plan = 'enterprise'"},
            ),
            (
                "pdi_properties",
                PropertyDefinition.Type.PERSON,
                {"type": "hogql", "key": "pdi.person.properties IS NOT NULL"},
            ),
            ("pdi_person", PropertyDefinition.Type.PERSON, {"type": "hogql", "key": "pdi.person IS NOT NULL"}),
            ("pdi", PropertyDefinition.Type.PERSON, {"type": "hogql", "key": "pdi IS NOT NULL"}),
            (
                "elements_property",
                PropertyDefinition.Type.EVENT,
                {"key": "$elements_chain", "type": "event", "operator": "icontains", "value": "button"},
                "$elements_chain",
            ),
            (
                "elements_alias",
                PropertyDefinition.Type.EVENT,
                {"type": "hogql", "key": "elements_chain != ''"},
                "$elements_chain",
            ),
            (
                "elements_texts",
                PropertyDefinition.Type.EVENT,
                {"type": "hogql", "key": "arrayExists(x -> x = 'example', elements_chain_texts)"},
                "$elements_chain",
            ),
            (
                "group_key",
                PropertyDefinition.Type.EVENT,
                {"key": "$group_0", "type": "event", "operator": "exact", "value": "example"},
                "$groups.organization",
            ),
            (
                "group_key_alias",
                PropertyDefinition.Type.EVENT,
                {"type": "hogql", "key": "`$group_0` = 'example'"},
                "$groups.organization",
            ),
        ]
    )
    def test_property_restrictions_apply_to_creation_and_delivery(
        self, _name: str, property_type: int, property_filter: dict[str, JsonValue], property_name: str = "plan"
    ) -> None:
        group_types = patch(
            "products.cdp.backend.mcp_event_properties.get_group_types_for_project",
            return_value=[{"group_type_index": 0, "group_type": "organization"}],
        )
        group_types.start()
        self.addCleanup(group_types.stop)
        subscription = self.subscribe()
        self.payload["arguments"] = {
            "project_id": self.team.pk,
            "filters": {
                "events": [{"id": "example_event", "type": "events"}],
                "properties": [property_filter],
            },
        }
        filtered_subscription = self.subscribe()
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=property_name, property_type="String", type=property_type
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        properties: dict[str, JsonValue] = {"plan": "enterprise"}
        if property_name == "$groups.organization":
            properties.update({"$groups": {"organization": "hidden"}, "$group_0": "hidden"})
        response = self.authorize(subscription, properties=properties)
        expected: dict[str, JsonValue] = (
            {} if property_type == PropertyDefinition.Type.EVENT and property_name == "plan" else {"plan": "enterprise"}
        )
        if property_name == "$groups.organization":
            expected["$groups"] = {}
        self.assertEqual(json.loads(response["body"])["data"]["properties"], expected)
        with self.assertRaises(PermissionDenied):
            self.authorize(filtered_subscription)
        with self.assertRaises(PermissionDenied):
            self.subscribe()

    @parameterized.expand(["test_account", "action", "child_action"])
    def test_filter_refresh_authorizes_new_filters_and_rejects_stale_queued_filters(self, source: str) -> None:
        original = [{"key": "plan", "type": "event", "operator": "exact", "value": "internal"}]
        updated = [{"key": "next_plan", "type": "event", "operator": "exact", "value": "internal"}]
        if source in ("action", "child_action"):
            action = Action.objects.create(
                team=self.team, name="Example action", steps_json=[{"event": "example_event", "properties": original}]
            )
            filters: dict[str, JsonValue] = {"actions": [{"id": str(action.id), "type": "actions"}]}
        else:
            self.team.test_account_filters = original
            self.team.save()
            filters = {"events": [{"id": "example_event", "type": "events"}], "filter_test_accounts": True}
        parent_subscription: MCPEventSubscription | None = None
        if source == "child_action":
            self.payload["arguments"] = {"project_id": self.team.pk, "filters": filters}
            parent_subscription = self.subscribe()
            self.team = Team.objects.create(
                organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
            )
        self.payload["arguments"] = {"project_id": self.team.pk, "filters": filters}
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        assert subscription.hog_function.filters is not None
        queued_bytecode = deepcopy(subscription.hog_function.filters["bytecode"])
        if source in ("action", "child_action"):
            action.steps_json = [{"event": "example_event", "properties": updated}]
            action.save()
            self.assertEqual(refresh_affected_hog_functions(action_id=action.pk), 2 if source == "child_action" else 1)
            if source == "child_action":
                assert parent_subscription is not None
                parent_subscription.refresh_from_db()
                assert parent_subscription.hog_function is not None
                assert parent_subscription.hog_function.filters is not None
                self.assertNotEqual(parent_subscription.hog_function.filters["bytecode"], queued_bytecode)
        else:
            self.team.test_account_filters = updated
            self.team.save()
            self.assertEqual(refresh_affected_hog_functions(team_id=self.team.pk), 1)
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        with self.assertRaises(PermissionDenied):
            self.authorize(subscription, filter_bytecode=queued_bytecode)
        subscription.refresh_from_db()
        self.assertTrue(subscription.active)
        self.authorize(subscription)
        next_definition = PropertyDefinition.objects.create(
            team=self.team, name="next_plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=next_definition, access_level="none")
        with self.assertRaises(PermissionDenied):
            self.authorize(subscription)
