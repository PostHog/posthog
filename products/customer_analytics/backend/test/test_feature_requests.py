from datetime import date
from typing import TypedDict, cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import OrganizationMembership, PersonalAPIKey, Team, UploadedMedia, User
from posthog.models.organization import AvailableFeature
from posthog.models.scoping import team_scope
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import (
    FeatureRequest,
    FeatureRequestAccountLink,
    FeatureRequestEvidence,
    FeatureRequestHistory,
    FeatureRequestProductArea,
)
from products.customer_analytics.backend.test.factories import create_account


class _EvidenceResponse(TypedDict):
    id: str
    summary: str
    image_ids: list[str]


class _AccountLinkResponse(TypedDict):
    id: str
    evidence: list[_EvidenceResponse]
    evidence_count: int


class _FeatureRequestResponse(TypedDict):
    id: str
    version: int
    account_links: list[_AccountLinkResponse]


class TestFeatureRequestsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.flag_patcher = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)
        self.account = create_account(team_id=self.team.id, name="Acme")
        self.area_one = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Product analytics",
            display_order=1,
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.area_two = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Session replay",
            display_order=2,
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.requests_url = f"/api/projects/{self.team.id}/feature_requests/"
        self.product_areas_url = f"/api/projects/{self.team.id}/feature_request_product_areas/"

    def _payload(self) -> dict[str, object]:
        return {
            "title": "Export account-level retention data",
            "description": "The customer needs this for their monthly reporting workflow.",
            "account_id": str(self.account.id),
            "product_area_ids": [str(self.area_one.id), str(self.area_two.id)],
            "idempotency_key": str(uuid4()),
        }

    def _set_access_level(self, user: User, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    def _add_evidence(
        self,
        *,
        request_id: str,
        version: int,
        account_link_id: str,
        summary: str,
        customer_quote: str = "",
        image_ids: list[str] | None = None,
    ) -> _FeatureRequestResponse:
        response = self.client.post(
            f"{self.requests_url}{request_id}/add_evidence/",
            {
                "expected_version": version,
                "account_link_id": account_link_id,
                "summary": summary,
                "customer_quote": customer_quote,
                "evidence_source": "conversation",
                "source_url": "",
                "requested_on": date.today().isoformat(),
                "image_ids": image_ids or [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return cast(_FeatureRequestResponse, response.json())

    def test_editor_can_create_and_view_a_request_with_multiple_product_areas_idempotently(self) -> None:
        payload = self._payload()

        created = self.client.post(self.requests_url, payload, format="json")
        repeated = self.client.post(self.requests_url, payload, format="json")
        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created.json()['id']}/")

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(repeated.status_code, status.HTTP_200_OK)
        self.assertEqual(repeated.json()["id"], created.json()["id"])
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()["count"], 1)
        self.assertTrue(listed.json()["results"][0]["can_update"])
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertTrue(retrieved.json()["can_update"])
        self.assertEqual(retrieved.json()["account_links"][0]["account"]["name"], "Acme")
        self.assertEqual(
            {area["name"] for area in retrieved.json()["product_areas"]},
            {"Product analytics", "Session replay"},
        )
        self.assertEqual(retrieved.json()["request_status"], "requested")
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 1)

    def test_create_can_include_initial_evidence(self) -> None:
        payload = self._payload()
        payload["evidence"] = {
            "evidence_source": "meeting",
            "requested_on": "2026-01-01",
        }

        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        evidence = response.json()["account_links"][0]["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["summary"], "")
        self.assertEqual(evidence[0]["evidence_source"], "meeting")
        self.assertEqual(evidence[0]["requested_on"], "2026-01-01")
        history = self.client.get(f"{self.requests_url}{response.json()['id']}/history/").json()
        initial_changes = {change["field"]: change for change in history[0]["changes"]}
        self.assertEqual(initial_changes["evidence"]["after"]["requested_on"], evidence[0]["requested_on"])

    def test_description_can_be_omitted_or_cleared(self) -> None:
        payload_without_description = self._payload()
        payload_without_description.pop("description")

        created_without_description = self.client.post(self.requests_url, payload_without_description, format="json")

        self.assertEqual(created_without_description.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created_without_description.json()["description"], "")

        created_with_description = self.client.post(self.requests_url, self._payload(), format="json").json()
        cleared = self.client.patch(
            f"{self.requests_url}{created_with_description['id']}/",
            {"expected_version": created_with_description["version"], "description": ""},
            format="json",
        )

        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        self.assertEqual(cleared.json()["description"], "")

    def test_create_rejects_relations_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        with team_scope(other_team.id):
            other_account = create_account(team_id=other_team.id, name="Other account")
            other_area = FeatureRequestProductArea.objects.for_team(other_team.id).create(
                team=other_team,
                name="Other area",
            )
        payload = self._payload()
        payload["account_id"] = str(other_account.id)
        payload["product_area_ids"] = [str(other_area.id)]

        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 0)

    def test_idempotency_retry_does_not_expose_a_request_for_an_inaccessible_account(self) -> None:
        payload = self._payload()
        created = self.client.post(self.requests_url, payload, format="json").json()
        restricted_editor = User.objects.create_and_join(
            self.organization,
            "restricted-feature-request-editor@example.com",
            "testtest",
        )
        self._set_access_level(restricted_editor, "editor")
        membership = OrganizationMembership.objects.get(user=restricted_editor, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(restricted_editor)

        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created['id']}/")
        history = self.client.get(f"{self.requests_url}{created['id']}/history/")
        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()["count"], 0)
        self.assertEqual(retrieved.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(history.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("Export account-level retention data", str(response.json()))

    def test_viewer_can_read_but_cannot_create(self) -> None:
        payload = self._payload()
        created = self.client.post(self.requests_url, payload, format="json").json()
        viewer = User.objects.create_and_join(self.organization, "feature-request-viewer@example.com", "testtest")
        self._set_access_level(viewer, "viewer")
        self.client.force_login(viewer)

        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created['id']}/")
        create_attempt = self.client.post(self.requests_url, self._payload(), format="json")
        update_attempt = self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {"expected_version": created["version"], "request_status": "planned"},
            format="json",
        )
        archive_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/archive/",
            {"expected_version": created["version"]},
            format="json",
        )
        evidence_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/add_evidence/",
            {
                "expected_version": created["version"],
                "account_link_id": created["account_links"][0]["id"],
                "summary": "Viewer must not add this.",
                "evidence_source": "conversation",
            },
            format="json",
        )

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertFalse(retrieved.json()["can_update"])
        self.assertEqual(create_attempt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_attempt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_attempt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(evidence_attempt.status_code, status.HTTP_403_FORBIDDEN)

    def test_account_viewer_cannot_mutate_request_or_evidence_as_customer_analytics_editor(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        with_evidence = self._add_evidence(
            request_id=created["id"],
            version=created["version"],
            account_link_id=created["account_links"][0]["id"],
            summary="Original evidence",
        )
        evidence_id = with_evidence["account_links"][0]["evidence"][0]["id"]
        other_account = create_account(team_id=self.team.id, name="Globex")
        account_viewer = User.objects.create_and_join(
            self.organization,
            "account-viewer-feature-request-editor@example.com",
            "testtest",
        )
        self._set_access_level(account_viewer, "editor")
        membership = OrganizationMembership.objects.get(user=account_viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(account_viewer)

        update_attempt = self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {"expected_version": with_evidence["version"], "request_status": "planned"},
            format="json",
        )
        add_account_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/add_account/",
            {
                "expected_version": with_evidence["version"],
                "account_id": str(other_account.id),
            },
            format="json",
        )
        add_evidence_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/add_evidence/",
            {
                "expected_version": with_evidence["version"],
                "account_link_id": created["account_links"][0]["id"],
                "summary": "Unauthorized evidence",
                "evidence_source": "conversation",
            },
            format="json",
        )
        update_evidence_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/update_evidence/",
            {
                "expected_version": with_evidence["version"],
                "evidence_id": evidence_id,
                "summary": "Unauthorized update",
                "evidence_source": "conversation",
            },
            format="json",
        )
        remove_evidence_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/remove_evidence/",
            {"expected_version": with_evidence["version"], "evidence_id": evidence_id},
            format="json",
        )

        self.assertEqual(
            [
                response.status_code
                for response in (
                    update_attempt,
                    add_account_attempt,
                    add_evidence_attempt,
                    update_evidence_attempt,
                    remove_evidence_attempt,
                )
            ],
            [status.HTTP_403_FORBIDDEN] * 5,
        )
        evidence = FeatureRequestEvidence.objects.for_team(self.team.id).get(id=evidence_id)
        self.assertEqual(evidence.summary, "Original evidence")

    def test_editor_groups_tracked_changes_once_and_stale_writes_fail(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        request_url = f"{self.requests_url}{created['id']}/"
        other_account = create_account(team_id=self.team.id, name="Globex")
        area_three = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Data warehouse",
            display_order=3,
        )

        updated = self.client.patch(
            request_url,
            {
                "expected_version": created["version"],
                "title": "Export account retention data",
                "request_status": "planned",
                "request_priority": "high",
                "account_ids": [str(other_account.id)],
                "product_area_ids": [str(self.area_two.id), str(area_three.id)],
            },
            format="json",
        )
        unchanged = self.client.patch(
            request_url,
            {"expected_version": updated.json()["version"], "request_status": "planned"},
            format="json",
        )
        invalid = self.client.patch(
            request_url,
            {"expected_version": updated.json()["version"], "product_area_ids": []},
            format="json",
        )
        stale = self.client.patch(
            request_url,
            {"expected_version": created["version"], "request_status": "completed"},
            format="json",
        )
        history = self.client.get(f"{request_url}history/")
        status_history = self.client.get(f"{request_url}status_history/")

        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.json()["request_status"], "planned")
        self.assertEqual(updated.json()["request_priority"], "high")
        self.assertEqual(updated.json()["version"], 2)
        self.assertEqual(unchanged.status_code, status.HTTP_200_OK)
        self.assertEqual(unchanged.json()["version"], 2)
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history.json()), 2)
        self.assertEqual(
            [change["field"] for change in history.json()[0]["changes"]],
            [
                "status",
                "priority",
                "accounts",
                "product_areas",
            ],
        )
        self.assertEqual(
            history.json()[0]["changes"],
            [
                {"field": "status", "before": "requested", "after": "planned"},
                {"field": "priority", "before": None, "after": "high"},
                {
                    "field": "accounts",
                    "before": [{"id": str(self.account.id), "name": "Acme"}],
                    "after": [{"id": str(other_account.id), "name": "Globex"}],
                },
                {
                    "field": "product_areas",
                    "before": [
                        {"id": str(self.area_one.id), "name": "Product analytics"},
                        {"id": str(self.area_two.id), "name": "Session replay"},
                    ],
                    "after": [
                        {"id": str(self.area_two.id), "name": "Session replay"},
                        {"id": str(area_three.id), "name": "Data warehouse"},
                    ],
                },
            ],
        )
        self.assertTrue(history.json()[1]["is_initial"])
        self.assertEqual(
            [change["field"] for change in history.json()[1]["changes"]],
            ["status", "priority", "accounts", "product_areas"],
        )
        self.assertEqual(
            [(entry["previous_status"], entry["request_status"]) for entry in status_history.json()],
            [("requested", "planned"), (None, "requested")],
        )
        self.assertEqual(FeatureRequestHistory.objects.for_team(self.team.id).count(), 2)

    def test_history_keeps_account_and_product_area_name_snapshots_after_renames(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")
        self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {
                "expected_version": created["version"],
                "account_id": str(other_account.id),
                "product_area_ids": [str(self.area_two.id)],
            },
            format="json",
        )

        self.account.name = "Acme renamed"
        self.account.save(update_fields=["name"])
        other_account.name = "Globex renamed"
        other_account.save(update_fields=["name"])
        self.area_one.name = "Product analytics renamed"
        self.area_one.save(update_fields=["name"])
        history = self.client.get(f"{self.requests_url}{created['id']}/history/").json()

        changes = {change["field"]: change for change in history[0]["changes"]}
        self.assertEqual(changes["accounts"]["before"][0]["name"], "Acme")
        self.assertEqual(changes["accounts"]["after"][0]["name"], "Globex")
        self.assertEqual(changes["product_areas"]["before"][0]["name"], "Product analytics")
        initial_changes = {change["field"]: change for change in history[1]["changes"]}
        self.assertEqual(initial_changes["accounts"]["after"][0]["name"], "Acme")
        self.assertEqual(initial_changes["product_areas"]["after"][0]["name"], "Product analytics")

    def test_history_redacts_snapshots_for_accounts_the_viewer_cannot_access(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")
        self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {
                "expected_version": created["version"],
                "account_ids": [str(other_account.id)],
            },
            format="json",
        )
        viewer = User.objects.create_and_join(
            self.organization,
            "restricted-feature-request-history-viewer@example.com",
            "testtest",
        )
        self._set_access_level(viewer, "viewer")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(viewer)

        response = self.client.get(f"{self.requests_url}{created['id']}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_changes = {change["field"]: change for change in response.json()[0]["changes"]}
        self.assertEqual(updated_changes["accounts"]["before"], [])
        self.assertEqual(
            updated_changes["accounts"]["after"],
            [{"id": str(other_account.id), "name": "Globex"}],
        )
        initial_changes = {change["field"]: change for change in response.json()[1]["changes"]}
        self.assertNotIn("accounts", initial_changes)
        self.assertNotIn(str(self.account.id), str(response.json()))
        self.assertNotIn("Acme", str(response.json()))

    def test_multiple_accounts_keep_separate_evidence_across_unlink_and_relink(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Aardvark")
        request_url = f"{self.requests_url}{created['id']}/"
        linked = self.client.patch(
            request_url,
            {
                "expected_version": created["version"],
                "account_ids": [str(self.account.id), str(other_account.id)],
            },
            format="json",
        ).json()
        links_by_account_id = {link["account"]["id"]: link for link in linked["account_links"]}

        with_acme_evidence = self._add_evidence(
            request_id=created["id"],
            version=linked["version"],
            account_link_id=links_by_account_id[str(self.account.id)]["id"],
            summary="Acme needs monthly exports.",
        )
        with_second_acme_evidence = self._add_evidence(
            request_id=created["id"],
            version=with_acme_evidence["version"],
            account_link_id=links_by_account_id[str(self.account.id)]["id"],
            summary="Acme repeated the request during renewal.",
        )
        with_other_evidence = self._add_evidence(
            request_id=created["id"],
            version=with_second_acme_evidence["version"],
            account_link_id=links_by_account_id[str(other_account.id)]["id"],
            summary="Aardvark needs a weekly export.",
        )
        listed = self.client.get(self.requests_url).json()["results"][0]

        self.assertTrue(all(not link["evidence"] for link in listed["account_links"]))
        self.assertEqual(
            {link["account"]["name"]: link["evidence_count"] for link in listed["account_links"]},
            {"Acme": 2, "Aardvark": 1},
        )

        unlinked = self.client.patch(
            request_url,
            {
                "expected_version": with_other_evidence["version"],
                "account_ids": [str(self.account.id)],
            },
            format="json",
        ).json()
        restored = self.client.patch(
            request_url,
            {
                "expected_version": unlinked["version"],
                "account_ids": [str(self.account.id), str(other_account.id)],
            },
            format="json",
        ).json()

        self.assertEqual(len(unlinked["account_links"]), 1)
        self.assertEqual(len(unlinked["account_links"][0]["evidence"]), 2)
        self.assertEqual([link["account"]["name"] for link in restored["account_links"]], ["Acme", "Aardvark"])
        restored_links = {link["account"]["id"]: link for link in restored["account_links"]}
        self.assertEqual(
            [evidence["summary"] for evidence in restored_links[str(self.account.id)]["evidence"]],
            ["Acme repeated the request during renewal.", "Acme needs monthly exports."],
        )
        self.assertEqual(
            restored_links[str(other_account.id)]["evidence"][0]["summary"], "Aardvark needs a weekly export."
        )
        other_link = FeatureRequestAccountLink.objects.for_team(self.team.id).get(account=other_account)
        self.assertIsNone(other_link.unlinked_at)
        self.assertEqual(
            FeatureRequestEvidence.objects.for_team(self.team.id).filter(account_link=other_link).count(), 1
        )

    def test_add_account_can_create_its_first_evidence_in_the_same_change(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")

        response = self.client.post(
            f"{self.requests_url}{created['id']}/add_account/",
            {
                "expected_version": created["version"],
                "account_id": str(other_account.id),
                "evidence": {
                    "summary": "Globex needs a weekly export.",
                    "customer_quote": "We need this before our Monday review.",
                    "evidence_source": "productboard",
                    "source_url": "https://example.com/meeting/1",
                    "requested_on": date.today().isoformat(),
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["version"], created["version"] + 1)
        links_by_account = {link["account"]["id"]: link for link in response.json()["account_links"]}
        self.assertEqual(
            links_by_account[str(other_account.id)]["evidence"][0]["summary"],
            "Globex needs a weekly export.",
        )
        self.assertEqual(links_by_account[str(other_account.id)]["evidence"][0]["evidence_source"], "productboard")
        history = self.client.get(f"{self.requests_url}{created['id']}/history/").json()
        self.assertEqual([change["field"] for change in history[0]["changes"]], ["accounts", "evidence"])

    def test_dated_evidence_sorts_before_undated_evidence(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        account_link_id = created["account_links"][0]["id"]
        undated = self.client.post(
            f"{self.requests_url}{created['id']}/add_evidence/",
            {
                "expected_version": created["version"],
                "account_link_id": account_link_id,
                "summary": "Undated evidence",
                "evidence_source": "conversation",
                "requested_on": None,
            },
            format="json",
        ).json()
        dated = self.client.post(
            f"{self.requests_url}{created['id']}/add_evidence/",
            {
                "expected_version": undated["version"],
                "account_link_id": account_link_id,
                "summary": "Dated evidence",
                "evidence_source": "conversation",
                "requested_on": "2026-01-01",
            },
            format="json",
        )

        self.assertEqual(dated.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["summary"] for item in dated.json()["account_links"][0]["evidence"]],
            ["Dated evidence", "Undated evidence"],
        )

    def test_image_only_evidence_requires_images_from_the_same_project(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        account_link_id = created["account_links"][0]["id"]
        image = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="request.png",
            content_type="image/png",
            media_location="feature-requests/request.png",
        )
        other_team = Team.objects.create(organization=self.organization)
        other_image = UploadedMedia.objects.create(
            team=other_team,
            created_by=self.user,
            file_name="other.png",
            content_type="image/png",
            media_location="feature-requests/other.png",
        )
        add_evidence_url = f"{self.requests_url}{created['id']}/add_evidence/"
        payload = {
            "expected_version": created["version"],
            "account_link_id": account_link_id,
            "summary": "",
            "customer_quote": "",
            "evidence_source": "conversation",
            "source_url": "",
            "image_ids": [str(other_image.id)],
        }

        rejected = self.client.post(add_evidence_url, payload, format="json")
        payload["image_ids"] = [str(image.id)]
        accepted = self.client.post(add_evidence_url, payload, format="json")

        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        self.assertEqual(accepted.json()["account_links"][0]["evidence"][0]["image_ids"], [str(image.id)])
        history = self.client.get(f"{self.requests_url}{created['id']}/history/").json()
        self.assertEqual(history[0]["changes"][0]["after"]["image_ids"], [str(image.id)])

    def test_evidence_updates_and_deletes_with_request_version_checks(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        account_link_id = created["account_links"][0]["id"]
        image = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="request.png",
            content_type="image/png",
            media_location="feature-requests/request.png",
        )
        with_evidence = self._add_evidence(
            request_id=created["id"],
            version=created["version"],
            account_link_id=account_link_id,
            summary="Initial summary",
            image_ids=[str(image.id)],
        )
        evidence_id = with_evidence["account_links"][0]["evidence"][0]["id"]
        update_url = f"{self.requests_url}{created['id']}/update_evidence/"

        stale = self.client.post(
            update_url,
            {
                "expected_version": created["version"],
                "evidence_id": evidence_id,
                "summary": "Stale summary",
                "evidence_source": "slack",
            },
            format="json",
        )
        updated = self.client.post(
            update_url,
            {
                "expected_version": with_evidence["version"],
                "evidence_id": evidence_id,
                "summary": "Updated summary",
                "customer_quote": "Please add this.",
                "evidence_source": "slack",
                "source_url": "https://example.com/thread/1",
            },
            format="json",
        ).json()
        deleted = self.client.post(
            f"{self.requests_url}{created['id']}/remove_evidence/",
            {
                "expected_version": updated["version"],
                "evidence_id": evidence_id,
            },
            format="json",
        )

        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(updated["account_links"][0]["evidence"][0]["summary"], "Updated summary")
        self.assertEqual(updated["account_links"][0]["evidence"][0]["image_ids"], [str(image.id)])
        self.assertEqual(deleted.status_code, status.HTTP_200_OK)
        self.assertEqual(deleted.json()["account_links"][0]["evidence"], [])
        self.assertFalse(FeatureRequestEvidence.objects.for_team(self.team.id).filter(id=evidence_id).exists())

    def test_viewer_only_receives_data_for_accessible_accounts(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")
        linked = self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {
                "expected_version": created["version"],
                "account_ids": [str(self.account.id), str(other_account.id)],
            },
            format="json",
        ).json()
        links = {link["account"]["id"]: link for link in linked["account_links"]}
        with_restricted_evidence = self._add_evidence(
            request_id=created["id"],
            version=linked["version"],
            account_link_id=links[str(self.account.id)]["id"],
            summary="Restricted account evidence",
        )
        self._add_evidence(
            request_id=created["id"],
            version=with_restricted_evidence["version"],
            account_link_id=links[str(other_account.id)]["id"],
            summary="Visible account evidence",
        )
        viewer = User.objects.create_and_join(
            self.organization,
            "restricted-feature-request-evidence-viewer@example.com",
            "testtest",
        )
        self._set_access_level(viewer, "viewer")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(viewer)

        response = self.client.get(f"{self.requests_url}{created['id']}/")
        history = self.client.get(f"{self.requests_url}{created['id']}/history/")
        restricted_filter = self.client.get(self.requests_url, {"account_ids": str(self.account.id)})
        visible_filter = self.client.get(self.requests_url, {"account_ids": str(other_account.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([link["account"]["name"] for link in response.json()["account_links"]], ["Globex"])
        self.assertEqual(response.json()["account_links"][0]["evidence"][0]["summary"], "Visible account evidence")
        self.assertNotIn("Restricted account evidence", str(response.json()))
        self.assertNotIn("Restricted account evidence", str(history.json()))
        self.assertTrue(all(entry["changes"] for entry in history.json()))
        self.assertEqual(restricted_filter.json()["count"], 0)
        self.assertEqual(visible_filter.json()["count"], 1)
        self.assertFalse(response.json()["can_update"])

    def test_list_combines_filters_orders_priorities_and_hides_archived_requests(self) -> None:
        first = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_creator = User.objects.create_and_join(
            self.organization, "feature-request-creator@example.com", "testtest"
        )
        self._set_access_level(other_creator, "editor")
        self.client.force_login(other_creator)
        second_payload = self._payload()
        second_payload["title"] = "Session replay export"
        second = self.client.post(self.requests_url, second_payload, format="json").json()
        self.client.force_login(self.user)
        third_payload = self._payload()
        third_payload["title"] = "Unprioritized export"
        third = self.client.post(self.requests_url, third_payload, format="json").json()
        self.client.patch(
            f"{self.requests_url}{first['id']}/",
            {
                "expected_version": first["version"],
                "request_status": "planned",
                "request_priority": "low",
            },
            format="json",
        )
        second_updated = self.client.patch(
            f"{self.requests_url}{second['id']}/",
            {"expected_version": second["version"], "request_priority": "high"},
            format="json",
        ).json()
        self.client.post(
            f"{self.requests_url}{second['id']}/archive/",
            {"expected_version": second_updated["version"]},
            format="json",
        )

        active = self.client.get(
            self.requests_url,
            {
                "search": "retention",
                "statuses": "planned,completed",
                "priorities": "low,medium",
                "product_area_ids": str(self.area_one.id),
                "account_ids": str(self.account.id),
                "request_ordering": "-priority",
            },
        )
        archived = self.client.get(self.requests_url, {"archive_state": "archived"})
        created_by_other = self.client.get(
            self.requests_url,
            {"archive_state": "all", "created_by_ids": str(other_creator.id)},
        )
        ordered = self.client.get(
            self.requests_url,
            {"archive_state": "all", "request_ordering": "-priority"},
        )

        self.assertEqual(active.status_code, status.HTTP_200_OK)
        self.assertEqual([request["id"] for request in active.json()["results"]], [first["id"]])
        self.assertEqual([request["id"] for request in archived.json()["results"]], [second["id"]])
        self.assertEqual([request["id"] for request in created_by_other.json()["results"]], [second["id"]])
        self.assertEqual(
            [request["id"] for request in ordered.json()["results"]],
            [second["id"], first["id"], third["id"]],
        )

    def test_archive_and_restore_preserve_links_and_history(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        request_url = f"{self.requests_url}{created['id']}/"
        updated = self.client.patch(
            request_url,
            {"expected_version": created["version"], "request_status": "completed"},
            format="json",
        ).json()

        archived = self.client.post(
            f"{request_url}archive/",
            {"expected_version": updated["version"]},
            format="json",
        )
        archived_update = self.client.patch(
            request_url,
            {"expected_version": archived.json()["version"], "title": "Cannot edit yet"},
            format="json",
        )
        restored = self.client.post(
            f"{request_url}restore/",
            {"expected_version": archived.json()["version"]},
            format="json",
        )
        history = self.client.get(f"{request_url}status_history/")

        self.assertTrue(archived.json()["is_archived"])
        self.assertEqual(archived_update.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(restored.json()["is_archived"])
        self.assertEqual(restored.json()["account_links"], created["account_links"])
        self.assertEqual(restored.json()["product_areas"], created["product_areas"])
        self.assertEqual(len(history.json()), 2)

    def test_scoped_personal_api_key_can_use_custom_actions(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="feature requests",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["customer_analytics:write"],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key_value}")

        added = self.client.post(
            f"{self.requests_url}{created['id']}/add_evidence/",
            {
                "expected_version": created["version"],
                "account_link_id": created["account_links"][0]["id"],
                "summary": "Requested during onboarding",
                "customer_quote": "",
                "evidence_source": "conversation",
                "source_url": "",
                "requested_on": None,
                "image_ids": [],
            },
            format="json",
        )
        history = self.client.get(f"{self.requests_url}{created['id']}/history/")

        self.assertEqual(added.status_code, status.HTTP_200_OK)
        self.assertEqual(added.json()["account_links"][0]["evidence_count"], 1)
        self.assertEqual(history.status_code, status.HTTP_200_OK)

    def test_feature_flag_blocks_the_api_without_deleting_data(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json")

        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            blocked = self.client.get(self.requests_url)

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 1)

    def test_product_area_list_rejects_invalid_include_inactive(self) -> None:
        response = self.client.get(self.product_areas_url, {"include_inactive": "sometimes"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_manager_can_create_and_update_product_areas(self) -> None:
        editor = User.objects.create_and_join(self.organization, "feature-request-editor@example.com", "testtest")
        self._set_access_level(editor, "editor")
        self.client.force_login(editor)
        denied = self.client.post(self.product_areas_url, {"name": "Surveys"}, format="json")

        manager = User.objects.create_and_join(self.organization, "feature-request-manager@example.com", "testtest")
        self._set_access_level(manager, "manager")
        self.client.force_login(manager)
        created = self.client.post(self.product_areas_url, {"name": "Surveys", "display_order": 3}, format="json")
        updated = self.client.patch(
            f"{self.product_areas_url}{created.json()['id']}/",
            {"name": "User surveys", "is_active": False},
            format="json",
        )

        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.json()["name"], "User surveys")
        self.assertFalse(updated.json()["is_active"])
