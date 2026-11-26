import json

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.oauth.application import PartnerReviewSerializer
from posthog.api.oauth.provisioning_review import (
    MAX_PARTNER_NOTES_IN_RUN_LOG,
    MAX_RUN_LOG_ENTRIES,
    PARTNER_NOTE_STEP,
    _append_to_run_log,
    decide_partner,
    send_partner_note,
    settle_review,
)
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.models.organization import Organization, OrganizationMembership
from posthog.scopes.exposure import UNPRIVILEGED_SCOPES


class TestOrganizationOAuthApplicationViewSet(APIBaseTest):
    expected_fields = {
        "id",
        "name",
        "client_id",
        "redirect_uris_list",
        "is_verified",
        "is_cimd_client",
        "provisioning_status",
        "provisioning_review",
        "created",
        "updated",
    }

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_app(self, organization, name="Test App", redirect_uris="https://example.com/callback", **kwargs):
        return OAuthApplication.objects.create(
            name=name,
            redirect_uris=redirect_uris,
            organization=organization,
            user=self.user,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            **kwargs,
        )

    def test_list_returns_apps_for_current_org(self):
        app = self._create_app(self.organization, name="My App")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(app.id))
        self.assertEqual(response.data["results"][0]["name"], "My App")

    def test_list_does_not_return_apps_from_other_org(self):
        other_org = Organization.objects.create(name="Other Org")
        self._create_app(self.organization, name="My App")
        self._create_app(other_org, name="Other App")

        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "My App")

    def test_list_returns_empty_when_no_apps(self):
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_response_contains_only_expected_fields(self):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data["results"][0].keys()), self.expected_fields)

    @parameterized.expand(["client_secret", "redirect_uris", "skip_authorization", "algorithm", "user"])
    def test_sensitive_field_not_exposed(self, field_name):
        self._create_app(self.organization)
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(field_name, response.data["results"][0])

    def test_redirect_uris_list_splits_space_separated_uris(self):
        self._create_app(self.organization, redirect_uris="https://a.com/cb https://b.com/cb")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.data["results"][0]["redirect_uris_list"], ["https://a.com/cb", "https://b.com/cb"])

    def test_list_ordered_by_most_recent_first(self):
        app1 = self._create_app(self.organization, name="First")
        app2 = self._create_app(self.organization, name="Second")
        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.data["results"][0]["id"], str(app2.id))
        self.assertEqual(response.data["results"][1]["id"], str(app1.id))

    def test_unauthenticated_request_is_rejected(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/api/organizations/@current/oauth_applications/")

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_read_only_no_create(self):
        response = self.client.post(
            "/api/organizations/@current/oauth_applications/",
            {"name": "New App"},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_detail_returns_an_app_of_the_current_org_only(self):
        app = self._create_app(self.organization)
        other = self._create_app(Organization.objects.create(name="Other Org"))

        own = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/")
        foreign = self.client.get(f"/api/organizations/@current/oauth_applications/{other.id}/")

        self.assertEqual(own.status_code, status.HTTP_200_OK)
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)

    def test_members_who_are_not_admins_are_refused(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._create_app(self.organization)

        response = self.client.get("/api/organizations/@current/oauth_applications/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("not_a_partner", False, ProvisioningConfig(), None, "not_a_partner"),
            ("in_review", True, ProvisioningConfig(), ProvisioningReviewStatus.PENDING, "in_review"),
            (
                "waiting_for_staff",
                True,
                ProvisioningConfig(),
                ProvisioningReviewStatus.NEEDS_HUMAN,
                "waiting_for_staff",
            ),
            ("on", True, ProvisioningConfig(active=True), ProvisioningReviewStatus.ACCEPTED, "on"),
            (
                "changes_requested",
                True,
                ProvisioningConfig(),
                ProvisioningReviewStatus.CHANGES_REQUESTED,
                "changes_requested",
            ),
            ("declined", True, ProvisioningConfig(), ProvisioningReviewStatus.DECLINED, "declined"),
            ("blocked", True, ProvisioningConfig(disabled=True), ProvisioningReviewStatus.REJECTED, "blocked"),
            # Every partner gate reads `active` alone, so this partner still provisions.
            ("active_and_disabled", True, ProvisioningConfig(active=True, disabled=True), None, "on"),
        ]
    )
    def test_provisioning_status_and_review(self, _name, is_partner, config, review_status, expected_status):
        app = self._create_app(
            self.organization,
            is_provisioning_partner=is_partner,
            _provisioning_config=config.model_dump(mode="json"),
        )
        if review_status is not None:
            CIMDProvisioningReview.objects.create(
                application=app,
                domain="example.com",
                status=review_status,
                reason="Research: legitimate 0.12, malicious 0.81",
                partner_message="Host the document on your product's domain, then register again.",
            )

        result = self.client.get("/api/organizations/@current/oauth_applications/").json()["results"][0]

        self.assertEqual(result["provisioning_status"], expected_status)
        if review_status is None:
            self.assertIsNone(result["provisioning_review"])
        else:
            self.assertEqual(
                set(result["provisioning_review"]),
                {"status", "opened_at", "decided_at", "partner_message", "timeline"},
            )
            self.assertEqual(result["provisioning_review"]["status"], review_status)
            self.assertNotIn("legitimate", str(result))

    @parameterized.expand(
        [
            ("declined", ProvisioningReviewStatus.DECLINED, False, 200),
            ("changes_requested", ProvisioningReviewStatus.CHANGES_REQUESTED, False, 200),
            ("waiting_for_staff", ProvisioningReviewStatus.NEEDS_HUMAN, False, 200),
            ("in_review", ProvisioningReviewStatus.PENDING, False, 400),
            ("accepted", ProvisioningReviewStatus.ACCEPTED, False, 400),
            ("blocked", ProvisioningReviewStatus.REJECTED, True, 400),
            ("declined_then_blocked_outside_the_review", ProvisioningReviewStatus.DECLINED, True, 400),
        ]
    )
    def test_review_note_sends_the_review_back_to_staff(self, _name, review_status, disabled, expected_code):
        app = self._create_app(
            self.organization,
            is_provisioning_partner=True,
            _provisioning_config=ProvisioningConfig(disabled=disabled).model_dump(mode="json"),
        )
        review = CIMDProvisioningReview.objects.create(application=app, domain="example.com", status=review_status)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/organizations/@current/oauth_applications/{app.id}/review_note/",
                {"note": "We moved the document to our own domain."},
            )

        self.assertEqual(response.status_code, expected_code, response.content)
        review.refresh_from_db()
        if expected_code == 200:
            self.assertEqual(response.json()["provisioning_status"], "waiting_for_staff")
            self.assertEqual(review.status, ProvisioningReviewStatus.NEEDS_HUMAN)
            self.assertIsNone(review.decided_at)
            self.assertIn("We moved the document to our own domain.", review.run_log[-1]["message"])
        else:
            self.assertEqual(response.json()["attr"], "note")
            self.assertEqual(review.status, review_status)
            self.assertEqual(review.run_log, [])
        app.refresh_from_db()
        self.assertEqual((app.provisioning.active, app.provisioning.disabled), (False, disabled))

    def test_detail_shows_enforced_redirect_uris_next_to_the_saved_document(self):
        app = self._create_app(
            self.organization, is_provisioning_partner=True, redirect_uris="https://builder.example.com/new-callback"
        )
        document = {
            "client_name": "Example Builder",
            "client_uri": "https://builder.example.com",
            "contacts": ["security@builder.example.com"],
            "redirect_uris": ["https://builder.example.com/callback"],
            "com.posthog": {"provisioning": True},
        }
        CIMDProvisioningReview.objects.create(application=app, domain="example.com", metadata_document=document)

        detail = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/").json()
        listed = self.client.get("/api/organizations/@current/oauth_applications/").json()["results"][0]

        registration = detail["registration"]
        self.assertEqual(
            {key: registration[key] for key in ("client_uri", "contacts", "redirect_uris", "organization_link")},
            {
                "client_uri": "https://builder.example.com",
                "contacts": ["security@builder.example.com"],
                "redirect_uris": ["https://builder.example.com/new-callback"],
                "organization_link": "this_organization",
            },
        )
        self.assertEqual(json.loads(registration["metadata_document"]), document)
        self.assertTrue(registration["needs_signing_key"])
        self.assertNotIn("registration", listed)

    @parameterized.expand(
        [
            ("no_scopes", [], True, None),
            ("default_sentinel_with_extras", ["@default", "llm_gateway:read"], True, "llm_gateway:read"),
            ("explicit_allow_list", ["insight:read"], False, None),
        ]
    )
    def test_detail_resolves_the_scopes_the_app_can_ask_for(self, _name, scopes, uses_default, extra):
        app = self._create_app(self.organization, is_provisioning_partner=True)
        app.scopes = scopes
        app.save(update_fields=["scopes"])

        registration = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/").json()[
            "registration"
        ]

        self.assertEqual(registration["uses_default_scopes"], uses_default)
        if uses_default:
            self.assertTrue(UNPRIVILEGED_SCOPES <= set(registration["scopes"]))
            self.assertNotIn("@default", registration["scopes"])
        else:
            self.assertEqual(registration["scopes"], scopes)
        if extra:
            self.assertIn(extra, registration["scopes"])

    def test_timeline_shows_decisions_messages_and_notes_without_internal_reasons(self):
        app = self._create_app(self.organization, is_provisioning_partner=True)
        CIMDProvisioningReview.objects.create(
            application=app,
            domain="example.com",
            run_log=[{"at": "2026-01-01T00:00:00+00:00", "step": "settled", "message": "Rejected: written before"}],
        )
        settle_review(
            str(app.pk),
            status=ProvisioningReviewStatus.NEEDS_HUMAN,
            stage=ProvisioningReviewStage.RESEARCH,
            reason="Research: malicious 0.81",
        )
        decide_partner(
            app,
            decision=ProvisioningReviewStatus.CHANGES_REQUESTED,
            reason="Staff: internal only",
            partner_message="Add a homepage.",
            actor="reviewer@example.com",
        )
        send_partner_note(app, user=self.user, note="We added one.")

        response = self.client.get(f"/api/organizations/@current/oauth_applications/{app.id}/")

        self.assertEqual(response.json()["provisioning_review"]["partner_message"], "Add a homepage.")
        timeline = response.json()["provisioning_review"]["timeline"]
        self.assertEqual(
            [(event["kind"], event["status"], event["message"], event["author"]) for event in timeline],
            [
                ("registered", None, "", ""),
                ("automated_review", "needs_human", "", ""),
                ("staff_decision", "changes_requested", "Add a homepage.", ""),
                ("partner_note", None, "We added one.", self.user.email),
            ],
        )
        for internal in ("malicious", "internal only", "reviewer@example.com", "written before"):
            self.assertNotIn(internal, response.content.decode())

        app.organization = Organization.objects.create(name="Next owner of the client ID")
        app.save(update_fields=["organization"])
        relinked = PartnerReviewSerializer(
            CIMDProvisioningReview.objects.select_related("application").get(application=app)
        ).data
        self.assertEqual(relinked["partner_message"], "")
        self.assertEqual(
            [(event["kind"], event["message"]) for event in relinked["timeline"]],
            [("registered", ""), ("automated_review", ""), ("staff_decision", "")],
        )

    def test_review_note_answers_a_decision_at_once_and_waits_between_notes_to_staff(self):
        app = self._create_app(self.organization, is_provisioning_partner=True)
        CIMDProvisioningReview.objects.create(
            application=app, domain="example.com", status=ProvisioningReviewStatus.DECLINED
        )
        url = f"/api/organizations/@current/oauth_applications/{app.id}/review_note/"

        answer = self.client.post(url, {"note": "We added a homepage."})
        first_note = self.client.post(url, {"note": "It describes the product."})
        second_note = self.client.post(url, {"note": "And the pricing."})

        self.assertEqual(answer.status_code, status.HTTP_200_OK, answer.content)
        self.assertEqual(first_note.status_code, status.HTTP_200_OK, first_note.content)
        self.assertEqual(second_note.status_code, status.HTTP_400_BAD_REQUEST)


class TestPartnerNotesInRunLog(SimpleTestCase):
    def test_notes_cannot_push_decisions_or_reopenings_out_of_a_full_run_log(self):
        decisions = [{"step": "settled", "message": f"Decision {index}"} for index in range(MAX_RUN_LOG_ENTRIES - 1)]
        reopening = {"step": PARTNER_NOTE_STEP, "previous_status": "declined", "message": "Asked again"}
        run_log = _append_to_run_log(list(decisions), reopening)

        for index in range(MAX_RUN_LOG_ENTRIES):
            run_log = _append_to_run_log(
                run_log, {"step": PARTNER_NOTE_STEP, "previous_status": "needs_human", "message": f"Note {index}"}
            )

        self.assertEqual(len(run_log), MAX_RUN_LOG_ENTRIES)
        self.assertEqual(
            [entry for entry in run_log if entry.get("previous_status") != "needs_human"], [*decisions, reopening]
        )

    def test_added_notes_keep_only_the_latest_ones(self):
        run_log: list[dict] = []

        for index in range(MAX_PARTNER_NOTES_IN_RUN_LOG + 5):
            run_log = _append_to_run_log(
                run_log, {"step": PARTNER_NOTE_STEP, "previous_status": "needs_human", "message": f"Note {index}"}
            )

        self.assertEqual(len(run_log), MAX_PARTNER_NOTES_IN_RUN_LOG)
        self.assertEqual(run_log[-1]["message"], f"Note {MAX_PARTNER_NOTES_IN_RUN_LOG + 4}")
