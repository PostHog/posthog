from typing import cast, Optional
from freezegun import freeze_time
import pytest
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework import status

from ee.models.license import License, LicenseManager
from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.models import EventProperty, Tag, ActivityLog
from posthog.models.property_definition import PropertyDefinition
from posthog.test.base import APIBaseTest


class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):
    def test_can_set_and_query_property_type_and_format(self):
        property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="a timestamp", property_type="DateTime"
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["property_type"] == "DateTime"

        query_list_response = self.client.get(f"/api/projects/@current/property_definitions")
        self.assertEqual(query_list_response.status_code, status.HTTP_200_OK)
        matches = [p["name"] for p in query_list_response.json()["results"] if p["name"] == "a timestamp"]
        assert len(matches) == 1

    def test_errors_on_invalid_property_type(self):
        with pytest.raises(IntegrityError):
            EnterprisePropertyDefinition.objects.create(
                team=self.team,
                name="a timestamp",
                property_type="not an allowed option",
            )

    def test_retrieve_existing_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        property.tagged_items.create(tag_id=tag.id)
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise property")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])

    def test_retrieve_create_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = PropertyDefinition.objects.create(team=self.team, name="property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_property = EnterprisePropertyDefinition.objects.all().first()
        property.refresh_from_db()
        self.assertEqual(enterprise_property.propertydefinition_ptr_id, property.id)  # type: ignore
        self.assertEqual(enterprise_property.name, property.name)  # type: ignore
        self.assertEqual(enterprise_property.team.id, property.team.id)  # type: ignore

    def test_search_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        EventProperty.objects.create(team=self.team, event="$pageview", property="enterprise property")
        enterprise_property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="enterprise property", description=""
        )
        enterprise_property.tagged_items.create(tag_id=tag.id)
        other_property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="other property", description=""
        )
        other_property.tagged_items.create(tag_id=tag.id)
        set_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="$set", description="")
        set_property.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enter")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        self.assertEqual(response_data["results"][0]["name"], "enterprise property")
        self.assertEqual(response_data["results"][0]["description"], "")
        self.assertEqual(response_data["results"][0]["tags"], ["deprecated"])

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enterprise")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        # always True if not scoping by event names
        self.assertEqual(response_data["results"][0]["is_seen_on_filtered_events"], None)

        # add event_names=['$pageview'] to get properties that have been seen by this event
        response = self.client.get(
            f"/api/projects/@current/property_definitions/?search=property&event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)
        self.assertEqual(response_data["results"][0]["name"], "enterprise property")
        self.assertEqual(response_data["results"][0]["is_seen_on_filtered_events"], True)
        self.assertEqual(response_data["results"][1]["name"], "other property")
        self.assertEqual(response_data["results"][1]["is_seen_on_filtered_events"], False)

        response = self.client.get(
            f"/api/projects/@current/property_definitions/?search=property&event_names=%5B%22%24pageview%22%5D&filter_by_event_names=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=er pr")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=bust")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=set")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

    def test_update_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"]},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(set(response_data["tags"]), {"official", "internal"})

        property.refresh_from_db()
        self.assertEqual(
            set(property.tagged_items.values_list("tag__name", flat=True)),
            {"official", "internal"},
        )

        activity_log: Optional[ActivityLog] = ActivityLog.objects.first()
        assert activity_log is not None
        self.assertEqual(activity_log.scope, "PropertyDefinition")
        self.assertEqual(activity_log.activity, "changed")
        self.assertEqual(activity_log.detail["name"], "enterprise property")
        self.assertEqual(activity_log.detail["type"], "event")
        self.assertEqual(activity_log.user, self.user)
        assert sorted(activity_log.detail["changes"], key=lambda x: x["field"]) == [
            {
                "action": "changed",
                "after": "This is a description.",
                "before": "",
                "field": "description",
                "type": "PropertyDefinition",
            },
            {
                "action": "changed",
                "after": ["official", "internal"],
                "before": [],
                "field": "tags",
                "type": "PropertyDefinition",
            },
        ]

    def test_update_property_definition_property_type(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )

        property = PropertyDefinition.objects.create(team=self.team, name="property")

        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            {"property_type": "Numeric"},
        )

        response_data = response.json()
        self.assertEqual(response_data["property_type"], "Numeric")
        self.assertEqual(response_data["is_numerical"], True)
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)

    def test_update_property_definition_non_numeric(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )

        property = PropertyDefinition.objects.create(
            team=self.team, name="property", property_type="Numeric", is_numerical=True
        )

        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            {"property_type": "DateTime"},
        )

        response_data = response.json()
        self.assertEqual(response_data["property_type"], "DateTime")
        self.assertEqual(response_data["is_numerical"], False)
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)

    def test_update_property_description_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn(
            "Self-hosted licenses are no longer available for purchase.",
            response.json()["detail"],
        )

    def test_update_property_tags_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"tags": ["test"]},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn(
            "Self-hosted licenses are no longer available for purchase.",
            response.json()["detail"],
        )

    def test_can_update_property_type_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"property_type": "DateTime"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["property_type"], "DateTime")

    def test_can_update_property_type_and_unchanged_keys_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={
                "id": property.id,
                "name": "enterprise property",
                "is_numerical": False,
                "property_type": "DateTime",
                "is_seen_on_filtered_events": None,
                "tags": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["property_type"], "DateTime")

    def test_cannot_update_more_than_property_type_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"property_type": "DateTime", "tags": ["test"]},
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
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn(
            "Self-hosted licenses are no longer available for purchase.",
            response.json()["detail"],
        )

    def test_filter_property_definitions(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        EnterprisePropertyDefinition.objects.create(team=self.team, name="plan")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="purchase")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="app_rating")

        response = self.client.get("/api/projects/@current/property_definitions/?properties=plan,app_rating")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["plan", "app_rating"])

    def test_event_property_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_can_get_property_verification_data(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None
        assert response.json()["updated_at"] == "2021-08-25T22:09:14.252000Z"

        query_list_response = self.client.get(f"/api/projects/@current/property_definitions")
        matches = [p["name"] for p in query_list_response.json()["results"] if p["name"] == "enterprise property"]
        assert len(matches) == 1

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_verify_then_unverify(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        # Verify the event
        self.client.patch(
            f"/api/projects/@current/property_definitions/{event.id}",
            {"verified": True},
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"

        # Unverify the event
        self.client.patch(
            f"/api/projects/@current/property_definitions/{event.id}",
            {"verified": False},
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_verify_then_verify_again_no_change(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        with freeze_time("2021-08-25T22:09:14.252Z"):
            self.client.patch(
                f"/api/projects/@current/property_definitions/{event.id}",
                {"verified": True},
            )
            response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"
        assert response.json()["updated_at"] == "2021-08-25T22:09:14.252000Z"

        with freeze_time("2021-10-26T22:09:14.252Z"):
            self.client.patch(
                f"/api/projects/@current/property_definitions/{event.id}",
                {"verified": True},
            )
            response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"  # Note `verified_at` did not change
        # updated_at automatically updates on every patch request
        assert response.json()["updated_at"] == "2021-10-26T22:09:14.252000Z"

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cannot_update_verified_meta_properties_directly(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        with freeze_time("2021-08-25T22:09:14.252Z"):
            self.client.patch(
                f"/api/projects/@current/property_definitions/{event.id}",
                {
                    "verified_by": self.user.id,
                    "verified_at": timezone.now(),
                },  # These properties are ignored by the serializer
            )
            response = self.client.get(f"/api/projects/@current/property_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_list_property_definitions(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )

        properties: list[dict] = [
            {"name": "1_when_verified", "verified": True},
            {"name": "2_when_verified", "verified": True},
            {"name": "3_when_verified", "verified": True},
            {"name": "4_when_verified", "verified": False},
            {"name": "5_when_verified", "verified": False},
            {"name": "6_when_verified", "verified": False},
        ]

        for property in properties:
            EnterprisePropertyDefinition.objects.create(team=self.team, name=property["name"])

        response = self.client.get("/api/projects/@current/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(properties))

        assert [(r["name"], r["verified"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]] == [
            ("1_when_verified", False, None),
            ("2_when_verified", False, None),
            ("3_when_verified", False, None),
            ("4_when_verified", False, None),
            ("5_when_verified", False, None),
            ("6_when_verified", False, None),
        ]

        for property in properties:
            definition = EnterprisePropertyDefinition.objects.filter(name=property["name"], team=self.team).first()
            if definition is None:
                raise AssertionError(f"Property definition {property['name']} not found")
            definition.verified = property["verified"] or False
            definition.save()

        response = self.client.get("/api/projects/@current/property_definitions/")

        assert [(r["name"], r["verified"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]] == [
            ("1_when_verified", True, None),
            ("2_when_verified", True, None),
            ("3_when_verified", True, None),
            ("4_when_verified", False, None),
            ("5_when_verified", False, None),
            ("6_when_verified", False, None),
        ]

        # We should prefer properties that have been seen on an event if that is available

        EventProperty.objects.get_or_create(team=self.team, event="$pageview", property="3_when_verified")
        EventProperty.objects.get_or_create(team=self.team, event="$pageview", property="4_when_verified")

        response = self.client.get("/api/projects/@current/property_definitions/?event_names=%5B%22%24pageview%22%5D")

        assert [(r["name"], r["verified"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]] == [
            ("3_when_verified", True, True),
            ("4_when_verified", False, True),
            ("1_when_verified", True, False),
            ("2_when_verified", True, False),
            ("5_when_verified", False, False),
            ("6_when_verified", False, False),
        ]
