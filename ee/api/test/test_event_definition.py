from datetime import datetime
from typing import cast, Optional, List, Dict, Any

import dateutil.parser
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.license import License, LicenseManager
from posthog.api.test.test_event_definition import capture_event, EventData
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models import Tag, ActivityLog, Team, User
from posthog.models.event_definition import EventDefinition
from posthog.test.base import APIBaseTest
from posthog.api.test.test_organization import create_organization


@freeze_time("2020-01-02")
class TestEventDefinitionEnterpriseAPI(APIBaseTest):
    demo_team: Team = None  # type: ignore
    user: User = None  # type: ignore

    """
    Ignoring the verified field we'd expect ordering purchase, watched_movie, entered_free_trial, $pageview
    With it we expect watched_movie, entered_free_trial, purchase, $pageview
    """
    EXPECTED_EVENT_DEFINITIONS: List[Dict[str, Any]] = [
        {"name": "purchase", "verified": None},
        {"name": "entered_free_trial", "verified": True},
        {"name": "watched_movie", "verified": True},
        {"name": "$pageview", "verified": None},
    ]

    @classmethod
    def setUpTestData(cls):
        cls.organization = create_organization(name="test org")
        cls.demo_team = create_team(organization=cls.organization)
        cls.user = create_user("user", "pass", cls.organization)

        for event_definition in cls.EXPECTED_EVENT_DEFINITIONS:
            EnterpriseEventDefinition.objects.create(name=event_definition["name"], team_id=cls.demo_team.pk)
            capture_event(
                event=EventData(
                    event=event_definition["name"],
                    team_id=cls.demo_team.pk,
                    distinct_id="abc",
                    timestamp=datetime(2020, 1, 1),
                    properties={},
                )
            )

    def test_list_event_definitions(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )

        response = self.client.get("/api/projects/@current/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(self.EXPECTED_EVENT_DEFINITIONS))

        self.assertEqual(
            [(r["name"], r["verified"]) for r in response.json()["results"]],
            [
                ("$pageview", False),
                ("entered_free_trial", False),
                ("purchase", False),
                ("watched_movie", False),
            ],
        )

        for event_definition in self.EXPECTED_EVENT_DEFINITIONS:
            definition = EnterpriseEventDefinition.objects.filter(
                name=event_definition["name"], team=self.demo_team
            ).first()
            if definition is None:
                raise AssertionError(f"Event definition {event_definition['name']} not found")
            definition.verified = event_definition["verified"] or False
            definition.save()

        response = self.client.get("/api/projects/@current/event_definitions/")

        assert [(r["name"], r["verified"]) for r in response.json()["results"]] == [
            ("$pageview", False),
            ("entered_free_trial", True),
            ("purchase", False),
            ("watched_movie", True),
        ]

    def test_retrieve_existing_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        tag = Tag.objects.create(name="deprecated", team_id=self.demo_team.id)
        event.tagged_items.create(tag_id=tag.id)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise event")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])
        self.assertEqual(response_data["owner"]["id"], self.user.id)

        self.assertAlmostEqual(
            (timezone.now() - dateutil.parser.isoparse(response_data["created_at"])).total_seconds(),
            0,
            delta=1,
        )
        self.assertIn("last_seen_at", response_data)

    def test_retrieve_create_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EventDefinition.objects.create(team=self.demo_team, name="event")
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_event = EnterpriseEventDefinition.objects.filter(id=event.id).first()
        event.refresh_from_db()
        self.assertEqual(enterprise_event.eventdefinition_ptr_id, event.id)  # type: ignore
        self.assertEqual(enterprise_event.name, event.name)  # type: ignore
        self.assertEqual(enterprise_event.team.id, event.team.id)  # type: ignore

    def test_search_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        enterprise_property = EnterpriseEventDefinition.objects.create(
            team=self.demo_team, name="enterprise event", owner=self.user
        )
        tag = Tag.objects.create(name="deprecated", team_id=self.demo_team.id)
        enterprise_property.tagged_items.create(tag_id=tag.id)
        regular_event = EnterpriseEventDefinition.objects.create(
            team=self.demo_team, name="regular event", owner=self.user
        )
        regular_event.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=enter")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(
            sorted([r["name"] for r in response_data["results"]]),
            ["entered_free_trial", "enterprise event"],
        )

        self.assertEqual(response_data["results"][1]["name"], "enterprise event")
        self.assertEqual(response_data["results"][1]["description"], "")
        self.assertEqual(response_data["results"][1]["tags"], ["deprecated"])
        self.assertEqual(response_data["results"][1]["owner"]["id"], self.user.id)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=enterprise")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=e ev")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(
            sorted([r["name"] for r in response_data["results"]]),
            ["$pageview", "enterprise event", "regular event"],
        )

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=bust")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

    def test_update_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"]},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(set(response_data["tags"]), {"official", "internal"})

        event.refresh_from_db()
        self.assertEqual(event.description, "This is a description.")
        self.assertEqual(
            set(event.tagged_items.values_list("tag__name", flat=True)),
            {"official", "internal"},
        )

        activity_log: Optional[ActivityLog] = ActivityLog.objects.first()
        assert activity_log is not None
        self.assertEqual(activity_log.scope, "EventDefinition")
        self.assertEqual(activity_log.activity, "changed")
        self.assertEqual(activity_log.detail["name"], "enterprise event")
        self.assertEqual(activity_log.user, self.user)
        assert sorted(activity_log.detail["changes"], key=lambda x: x["field"]) == [
            {
                "action": "changed",
                "after": "This is a description.",
                "before": "",
                "field": "description",
                "type": "EventDefinition",
            },
            {
                "action": "changed",
                "after": ["official", "internal"],
                "before": [],
                "field": "tags",
                "type": "EventDefinition",
            },
        ]

    def test_update_event_without_license(self):
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}",
            data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn(
            "Self-hosted licenses are no longer available for purchase.",
            response.json()["detail"],
        )

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}",
            data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn(
            "Self-hosted licenses are no longer available for purchase.",
            response.json()["detail"],
        )

    def test_can_get_event_verification_data(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None
        assert response.json()["updated_at"] == "2020-01-02T00:00:00Z"

        query_list_response = self.client.get(f"/api/projects/@current/event_definitions")
        matches = [p["name"] for p in query_list_response.json()["results"] if p["name"] == "enterprise event"]
        assert len(matches) == 1

    def test_verify_then_unverify(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        # Verify the event
        self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": True})
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2020-01-02T00:00:00Z"

        # Unverify the event
        self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": False})
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_verify_then_verify_again_no_change(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert self.user.team.pk == self.demo_team.pk

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        patch_result = self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": True})
        self.assertEqual(patch_result.status_code, status.HTTP_200_OK, patch_result.json())

        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2020-01-02T00:00:00Z"
        assert response.json()["updated_at"] == "2020-01-02T00:00:00Z"

        with freeze_time("2020-01-02T00:01:00Z"):
            self.client.patch(
                f"/api/projects/@current/event_definitions/{event.id}",
                {"verified": True},
            )
            response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2020-01-02T00:00:00Z"  # Note `verified_at` did not change
        # updated_at automatically updates on every patch request
        assert response.json()["updated_at"] == "2020-01-02T00:01:00Z"

    def test_cannot_update_verified_meta_properties_directly(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        with freeze_time("2020-01-02T00:01:00Z"):
            self.client.patch(
                f"/api/projects/@current/event_definitions/{event.id}",
                {
                    "verified_by": self.user.id,
                    "verified_at": timezone.now(),
                },  # These properties are ignored by the serializer
            )
            response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_event_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="enterprise event")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}",
            data={"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_event_type_event(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        EnterpriseEventDefinition.objects.create(team=self.demo_team, name="rated_app")
        EnterpriseEventDefinition.objects.create(team=self.demo_team, name="installed_app")

        response = self.client.get("/api/projects/@current/event_definitions/?search=app&event_type=event")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
