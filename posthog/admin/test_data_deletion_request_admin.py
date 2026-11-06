from datetime import datetime, timedelta

import time_machine
from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from bs4 import BeautifulSoup
from parameterized import parameterized

from posthog.admin.admins.data_deletion_request_admin import DataDeletionRequestAdmin, dagster_run_url
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType


@time_machine.travel("2025-01-15 12:00:00", tick=False)
class TestDataDeletionRequestModelValidation(BaseTest):
    def test_person_removal_rejects_person_properties_field(self):
        from django.core.exceptions import ValidationError

        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PERSON_REMOVAL,
            person_uuids=["00000000-0000-0000-0000-000000000001"],
            person_drop_profiles=True,
            person_properties=["email"],
        )
        with self.assertRaises(ValidationError) as cm:
            obj.clean()
        self.assertIn("person_properties", cm.exception.message_dict)

    def test_person_removal_without_person_properties_is_valid(self):
        from django.core.exceptions import ValidationError

        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PERSON_REMOVAL,
            person_uuids=["00000000-0000-0000-0000-000000000001"],
            person_drop_profiles=True,
            person_properties=[],
        )
        try:
            obj.clean()
        except ValidationError as exc:
            if "person_properties" in (exc.message_dict if hasattr(exc, "message_dict") else {}):
                self.fail(f"clean() raised unexpected ValidationError for person_properties: {exc}")

    @parameterized.expand(
        [
            ("properties_only", ["$ip"], []),
            ("person_properties_only", [], ["email"]),
            ("both", ["$ip"], ["email"]),
        ]
    )
    def test_property_removal_does_not_validate_field_presence_at_model_level(
        self, _name, properties, person_properties
    ):
        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=properties,
            person_properties=person_properties,
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
        )
        from django.core.exceptions import ValidationError

        try:
            obj.clean()
        except ValidationError as exc:
            msg_dict = exc.message_dict if hasattr(exc, "message_dict") else {}
            self.assertNotIn("properties", msg_dict)
            self.assertNotIn("person_properties", msg_dict)


@time_machine.travel("2026-11-06T12:00:00Z", tick=False)
@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminChangePage(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_change_page_is_read_only_and_links_to_the_console(self):
        request = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )

        response = self.client.get(f"/admin/posthog/datadeletionrequest/{request.pk}/change/")
        posted = self.client.post(f"/admin/posthog/datadeletionrequest/{request.pk}/change/", {"notes": "edited"})

        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertIsNone(soup.select_one("textarea, input[name=_save]"))
        self.assertIsNotNone(soup.select_one(f'a[href="/admin/console/deletion-requests/{request.pk}/"]'))
        self.assertEqual(posted.status_code, 403)
        request.refresh_from_db()
        self.assertEqual(request.notes, "")

    @parameterized.expand([("existing_team", True), ("deleted_team", False)])
    def test_change_view_shows_team_and_organization(self, _name, team_exists):
        team_id = self.team.id if team_exists else 999999
        request = DataDeletionRequest.objects.create(
            team_id=team_id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
        )

        response = self.client.get(f"/admin/posthog/datadeletionrequest/{request.pk}/change/")

        self.assertEqual(response.status_code, 200)
        team_field = BeautifulSoup(response.content, "html.parser").select_one(".field-team_details .readonly")
        assert team_field is not None
        links = {a.get("href"): a.get_text() for a in team_field.select("a")}
        if team_exists:
            self.assertEqual(
                links,
                {
                    reverse("admin:posthog_team_change", args=[self.team.id]): str(self.team.id),
                    reverse("admin:posthog_organization_change", args=[self.organization.id]): str(
                        self.organization.id
                    ),
                },
            )
            self.assertIn(self.team.name, team_field.get_text())
            self.assertIn(self.organization.name, team_field.get_text())
        else:
            self.assertEqual(links, {})
            self.assertIn(f"{team_id} (team not found)", team_field.get_text())


class TestDagsterRunLink(SimpleTestCase):
    RUN_ID = "f5f3a611-4be8-48bc-9b29-ff8b06d01189"

    @parameterized.expand(
        [
            ("cloud_us", None, "US", f"https://posthog.dagster.cloud/prod-us/runs/{RUN_ID}"),
            ("cloud_eu", None, "EU", f"https://posthog.dagster.cloud/prod-eu/runs/{RUN_ID}"),
            ("dev", None, "DEV", f"https://posthog.dagster.cloud/dev/runs/{RUN_ID}"),
            ("lowercase_deployment", None, "eu", f"https://posthog.dagster.cloud/prod-eu/runs/{RUN_ID}"),
            ("domain_takes_precedence", "dagster.example.com", "EU", f"https://dagster.example.com/runs/{RUN_ID}"),
            ("local", None, None, None),
            ("unknown_deployment", None, "E2E", None),
        ]
    )
    def test_dagster_run_url(self, _name, dagster_domain, cloud_deployment, expected):
        with override_settings(DAGSTER_DOMAIN=dagster_domain, CLOUD_DEPLOYMENT=cloud_deployment):
            self.assertEqual(dagster_run_url(self.RUN_ID), expected)

    @override_settings(DAGSTER_DOMAIN=None, CLOUD_DEPLOYMENT="EU")
    def test_admin_renders_run_id_as_link(self):
        admin_obj = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())
        rendered = admin_obj.last_dagster_run(DataDeletionRequest(last_dagster_run_id=self.RUN_ID))
        self.assertIn(f'href="https://posthog.dagster.cloud/prod-eu/runs/{self.RUN_ID}"', rendered)

    @override_settings(DAGSTER_DOMAIN=None, CLOUD_DEPLOYMENT=None)
    def test_admin_renders_bare_run_id_when_deployment_unknown(self):
        admin_obj = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())
        rendered = admin_obj.last_dagster_run(DataDeletionRequest(last_dagster_run_id=self.RUN_ID))
        self.assertEqual(rendered, self.RUN_ID)

    def test_admin_renders_placeholder_when_never_executed(self):
        admin_obj = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())
        self.assertEqual(admin_obj.last_dagster_run(DataDeletionRequest()), "—")
