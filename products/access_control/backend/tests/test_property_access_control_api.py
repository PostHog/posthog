from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.test.persons import create_person

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel


def _enable_property_access_control(organization):
    organization.available_product_features = [
        {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    organization.save()


class TestClickhouseEventSerializerPropertyAccess(BaseTest):
    def setUp(self):
        super().setUp()
        _enable_property_access_control(self.organization)
        self.event_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_event_prop",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        self.person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="email",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def _make_event(self) -> dict:
        import json
        from datetime import datetime

        return {
            "uuid": "test-uuid-1234",
            "event": "$pageview",
            "properties": json.dumps(
                {
                    "secret_event_prop": "hidden_value",
                    "public_prop": "visible_value",
                    "$browser": "Chrome",
                }
            ),
            "distinct_id": "user1",
            "timestamp": datetime(2024, 1, 1),
            "elements_chain": "",
        }

    def test_no_restrictions_returns_all_properties(self):
        event = self._make_event()
        data = ClickhouseEventSerializer(event, context={}).data
        assert "secret_event_prop" in data["properties"]
        assert "public_prop" in data["properties"]

    def test_restricted_event_property_stripped_from_response(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        event = self._make_event()
        data = ClickhouseEventSerializer(event, context={"restricted_event_properties": {"secret_event_prop"}}).data
        assert "secret_event_prop" not in data["properties"]
        assert "public_prop" in data["properties"]
        assert "$browser" in data["properties"]

    def test_restricted_person_property_stripped_from_embedded_person(self):
        person = create_person(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "secret@example.com", "name": "Test User"},
        )
        event = self._make_event()
        data = ClickhouseEventSerializer(
            event,
            context={
                "people": {"user1": person},
                "restricted_person_properties": {"email"},
            },
        ).data
        assert "email" not in data["person"]["properties"]
        assert "name" in data["person"]["properties"]


class TestPersonSerializerPropertyAccess(BaseTest):
    def setUp(self):
        super().setUp()
        _enable_property_access_control(self.organization)
        self.person = create_person(
            team=self.team,
            distinct_ids=["user1"],
            properties={
                "email": "test@example.com",
                "secret_prop": "hidden_value",
                "public_prop": "visible_value",
            },
        )
        self.person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_prop",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def test_no_restrictions_returns_all_properties(self):
        from posthog.api.person import PersonSerializer

        data = PersonSerializer(self.person, context={"get_team": lambda: self.team}).data
        assert "secret_prop" in data["properties"]
        assert "public_prop" in data["properties"]

    def test_restricted_person_property_stripped(self):
        from posthog.api.person import PersonSerializer

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        data = PersonSerializer(
            self.person,
            context={
                "get_team": lambda: self.team,
                "restricted_person_properties": {"secret_prop"},
            },
        ).data
        assert "secret_prop" not in data["properties"]
        assert "public_prop" in data["properties"]
        assert "email" in data["properties"]

    def test_read_access_does_not_strip_property(self):
        from posthog.api.person import PersonSerializer

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.READ.value,
        )
        data = PersonSerializer(
            self.person,
            context={
                "get_team": lambda: self.team,
                # READ level means it grants access, so it should not be in restricted set
            },
        ).data
        assert "secret_prop" in data["properties"]


class TestPropertyAccessControlHelpers(BaseTest):
    def setUp(self):
        super().setUp()
        _enable_property_access_control(self.organization)
        self.person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_prop",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def test_get_restricted_property_names(self):
        from products.access_control.backend.property_access_control import get_restricted_property_names

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        restricted = get_restricted_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        assert restricted == {"secret_prop"}

    def test_get_restricted_property_names_empty_for_read_write(self):
        from products.access_control.backend.property_access_control import get_restricted_property_names

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )
        restricted = get_restricted_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        assert restricted == set()

    def test_get_non_writable_property_names(self):
        from products.access_control.backend.property_access_control import get_non_writable_property_names

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.READ.value,
        )
        non_writable = get_non_writable_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        assert non_writable == {"secret_prop"}

    def test_get_non_writable_property_names_empty_for_read_write(self):
        from products.access_control.backend.property_access_control import get_non_writable_property_names

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )
        non_writable = get_non_writable_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        assert non_writable == set()

    def test_get_non_writable_includes_none_level(self):
        from products.access_control.backend.property_access_control import get_non_writable_property_names

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        non_writable = get_non_writable_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        assert non_writable == {"secret_prop"}

    def test_strip_restricted_properties(self):
        from products.access_control.backend.property_access_control import strip_restricted_properties

        props = {"secret": "hidden", "public": "visible", "other": "also_visible"}
        result = strip_restricted_properties(props, {"secret"})
        assert result == {"public": "visible", "other": "also_visible"}

    def test_strip_restricted_properties_empty_restricted(self):
        from products.access_control.backend.property_access_control import strip_restricted_properties

        props = {"a": 1, "b": 2}
        result = strip_restricted_properties(props, set())
        assert result == {"a": 1, "b": 2}
