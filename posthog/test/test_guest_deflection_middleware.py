from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.notebooks.backend.models import Notebook
from products.surveys.backend.models import Survey

from ee.models.rbac.access_control import AccessControl


class TestGuestDeflectionMiddleware(APIBaseTest):
    """HTTP-level coverage of the guest deflection rules.

    Setup wires up:
    - one guest user with an optional grant list
    - one granted notebook + one ungranted notebook as a foil
    """

    def setUp(self) -> None:
        super().setUp()
        # Advanced permissions feature is required for the UserAccessControl layer to honor
        # per-object AC rows. Without it the AC layer short-circuits and guests look no
        # different from members without grants.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.granted_notebook = Notebook.objects.create(team=self.team, title="Granted", short_id="GRNT0001")
        self.ungranted_notebook = Notebook.objects.create(team=self.team, title="Ungranted", short_id="HIDD0001")

    def _login_guest(self) -> None:
        self.client.force_login(self.guest_user)

    def _login_regular(self) -> None:
        self.client.force_login(self.user)

    def _grant_notebook(self) -> None:
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.granted_notebook.short_id,
            created_by=self.user,
        )

    def test_non_guest_user_is_never_deflected(self) -> None:
        self._login_regular()
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertNotEqual(res.status_code, 404)

    def test_guest_user_without_grants_is_deflected_from_api(self) -> None:
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_guest_user_without_grants_is_redirected_on_spa_route(self) -> None:
        # `?from=login` is appended so the landing scene knows this is a system-driven
        # deflection — single-grant guests auto-jump to their resource on this kind of
        # redirect; explicit header navigation (no flag) shows the list.
        self._login_guest()
        res = self.client.get(f"/project/{self.team.pk}/experiments", follow=False)
        self.assertEqual(res.status_code, status.HTTP_302_FOUND)
        self.assertEqual(res["Location"], "/guest?from=login")

    def test_guest_landing_page_is_not_deflected(self) -> None:
        self._login_guest()
        res = self.client.get("/guest", follow=False)
        self.assertNotEqual(res.status_code, status.HTTP_302_FOUND)

    def test_themes_metadata_is_allowed_for_guest_with_any_grant(self) -> None:
        self._grant_notebook()
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/data_color_themes/")
        self.assertNotEqual(res.status_code, 404)

    def test_themes_metadata_post_is_deflected(self) -> None:
        self._grant_notebook()
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/data_color_themes/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_users_me_is_always_allowed(self) -> None:
        self._login_guest()
        res = self.client.get("/api/users/@me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_organizations_current_is_always_allowed(self) -> None:
        self._login_guest()
        res = self.client.get("/api/organizations/@current/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("annotations", "projects"),
            ("cohorts", "projects"),
            ("tags", "projects"),
            ("insight_variables", "environments"),
            ("quick_filters", "environments"),
            ("data_color_themes", "environments"),
        ]
    )
    def test_metadata_endpoints_require_any_grant(self, endpoint: str, scope: str) -> None:
        self._login_guest()
        url = f"/api/{scope}/{self.team.pk}/{endpoint}/"
        res_without_grant = self.client.get(url)
        self.assertEqual(res_without_grant.status_code, status.HTTP_404_NOT_FOUND)

        self._grant_notebook()
        res_with_grant = self.client.get(url)
        self.assertNotEqual(res_with_grant.status_code, 404)


class TestGuestDeflectionCrossOrgScoping(APIBaseTest):
    """Guest deflection must scope to the org the request targets.

    A user who is a guest of org A AND a regular member of org B must NOT be
    deflected on org B's paths — guest behavior only applies in the org where
    they are actually a guest.
    """

    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(is_guest=True)
        from posthog.models import Organization, Team

        self.org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.user,
            is_guest=False,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.team_b = Team.objects.create_with_data(organization=self.org_b, name="Team B", initiating_user=self.user)
        self.notebook_b = Notebook.objects.create(team=self.team_b, title="Org B notebook", short_id="ORGB0001")

    def test_guest_in_other_org_is_not_deflected_on_target_org_paths(self) -> None:
        self.client.force_login(self.user)
        res = self.client.get(f"/api/projects/{self.team_b.pk}/notebooks/{self.notebook_b.short_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_guest_in_same_org_is_deflected_on_ungranted_paths(self) -> None:
        self.client.force_login(self.user)
        ungranted_notebook = Notebook.objects.create(team=self.team, title="Ungranted", short_id="UNGR0001")
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionRuleLoop(APIBaseTest):
    """First matching rule decides the outcome — a matched-but-denied rule must
    deflect rather than letting subsequent rules try the same path."""

    def test_first_matched_rule_decides_even_when_a_later_rule_would_allow(self) -> None:
        from django.http import HttpRequest

        from posthog.middleware_guest import AlwaysAllowed, GuestDeflectionMiddleware, GuestRule

        class AlwaysDenies(GuestRule):
            def allows(self, request, user, match) -> bool:
                return False

        guest = User.objects.create_user(email="ruleloop-guest@example.com", first_name="G", password="p")
        OrganizationMembership.objects.create(organization=self.organization, user=guest, is_guest=True)

        request = HttpRequest()
        request.method = "GET"
        request.path = f"/api/projects/{self.team.pk}/notebooks/foo/"
        request.user = guest

        forwarded = {"called": False}

        def fake_get_response(_req):
            forwarded["called"] = True
            return None

        middleware = GuestDeflectionMiddleware(fake_get_response)
        middleware._rules = [
            AlwaysDenies(r"^/api/projects/\d+/notebooks/.*$"),
            AlwaysAllowed(r"^/api/projects/\d+/notebooks/.*$"),
        ]

        response = middleware(request)
        self.assertFalse(forwarded["called"])
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionNotebookGrants(APIBaseTest):
    """Notebook grants address the resource by `short_id` in the URL — Notebook's PK
    is a UUID, not an integer, so the middleware must resolve through `short_id` only.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="notebook-guest@example.com", first_name="N", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.granted_notebook = Notebook.objects.create(team=self.team, title="Granted", short_id="GRNT0001")
        self.ungranted_notebook = Notebook.objects.create(team=self.team, title="Hidden", short_id="HIDD0001")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.granted_notebook.short_id,
            created_by=self.user,
            access_level="viewer",
        )

    def test_granted_notebook_short_id_url_is_forwarded(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.granted_notebook.short_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_notebook_short_id_url_is_deflected(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_notebook_uuid_in_url_is_deflected(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.granted_notebook.id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionEmbeddedNodeResources(APIBaseTest):
    """Each cascadeable embedded notebook node has a sibling middleware rule that
    forwards `/api/.../<embedded-resource>/<id>/` when the guest has an AC row on
    that embedded resource (typically written by `cascade_grants_for_notebook`).
    These tests verify the deflect/forward decision at the URL layer in isolation —
    by writing the AC row directly rather than going through the cascade — so a
    failure here clearly fingers the middleware rule, not the cascade.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="embed-guest@example.com", first_name="E", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        self.client.force_login(self.guest_user)

    def _grant(self, resource: str, resource_id: str) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )

    def test_granted_feature_flag_is_forwarded(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="grnt-flag", name="Granted")
        self._grant("feature_flag", str(flag.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.pk}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_feature_flag_is_deflected(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="hidd-flag", name="Hidden")
        res = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_experiment_is_forwarded(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="exp-flag", name="X")
        exp = Experiment.objects.create(team=self.team, name="E", feature_flag=flag)
        self._grant("experiment", str(exp.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/experiments/{exp.pk}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_experiment_is_deflected(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="exp-flag-2", name="X2")
        exp = Experiment.objects.create(team=self.team, name="E2", feature_flag=flag)
        res = self.client.get(f"/api/projects/{self.team.pk}/experiments/{exp.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_cohort_is_forwarded(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="C")
        self._grant("cohort", str(cohort.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/cohorts/{cohort.pk}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_cohort_is_deflected(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Hidden cohort")
        res = self.client.get(f"/api/projects/{self.team.pk}/cohorts/{cohort.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_survey_is_forwarded(self) -> None:
        survey = Survey.objects.create(team=self.team, name="S")
        self._grant("survey", str(survey.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/surveys/{survey.pk}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_survey_is_deflected(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Hidden survey")
        res = self.client.get(f"/api/projects/{self.team.pk}/surveys/{survey.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_early_access_feature_is_forwarded(self) -> None:
        # The URL form is singular — `/early_access_feature/<uuid>/`.
        flag = FeatureFlag.objects.create(team=self.team, key="eaf-flag", name="EAF flag")
        eaf = EarlyAccessFeature.objects.create(team=self.team, name="EAF", stage="draft", feature_flag=flag)
        self._grant("early_access_feature", str(eaf.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/early_access_feature/{eaf.pk}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_early_access_feature_is_deflected(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="eaf-flag-2", name="EAF flag 2")
        eaf = EarlyAccessFeature.objects.create(team=self.team, name="Hidden EAF", stage="draft", feature_flag=flag)
        res = self.client.get(f"/api/projects/{self.team.pk}/early_access_feature/{eaf.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_session_recording_is_forwarded(self) -> None:
        # SessionRecording URL form is `session_id` (posthog-js generated); the AC
        # layer addresses by the UUID PK. The cascade resolves session_id → PK before
        # writing AC rows, so this test mirrors that and grants by PK.
        session_id = "0195b7c5-1c8a-7000-aaaa-aaaaaaaaaaaa"
        rec = SessionRecording.objects.create(team=self.team, session_id=session_id)
        self._grant("session_recording", str(rec.id))
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recordings/{session_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_session_recording_is_deflected(self) -> None:
        session_id = "0195b7c5-1c8a-7000-aaaa-bbbbbbbbbbbb"
        SessionRecording.objects.create(team=self.team, session_id=session_id)
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recordings/{session_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_session_recording_playlist_is_forwarded(self) -> None:
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00111", name="P")
        self._grant("session_recording_playlist", str(playlist.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recording_playlists/{playlist.short_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_session_recording_playlist_is_deflected(self) -> None:
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00222", name="P2")
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recording_playlists/{playlist.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_session_recording_playlist_list_filter_by_short_id_is_forwarded(self) -> None:
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00333", name="P3")
        self._grant("session_recording_playlist", str(playlist.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recording_playlists/?short_id={playlist.short_id}")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_session_recording_playlist_list_without_short_id_filter_is_deflected(self) -> None:
        # The list endpoint is gated to `?short_id=<granted>` — without the filter the
        # list would enumerate, which the FE never does for guests.
        SessionRecordingPlaylist.objects.create(team=self.team, short_id="PSI00444", name="P4")
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recording_playlists/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand([("find",), ("related",)])
    def test_groups_resolver_endpoints_require_any_grant(self, endpoint: str) -> None:
        # GET /api/.../groups/find and /groups/related are read-only resolvers used by
        # ph-group / ph-group-properties / ph-related-groups embeds. Same gate as the
        # other team-scoped metadata reads.
        url = f"/api/environments/{self.team.pk}/groups/{endpoint}"
        res_no_grant = self.client.get(url)
        self.assertEqual(res_no_grant.status_code, status.HTTP_404_NOT_FOUND)

        # Any grant unlocks team-scoped metadata reads — use a notebook AC row as proxy.
        notebook = Notebook.objects.create(team=self.team, title="N", short_id="GRP00001")
        AccessControl.objects.create(
            team=self.team,
            resource="notebook",
            resource_id=str(notebook.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        res_with_grant = self.client.get(url)
        self.assertNotEqual(res_with_grant.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_feature_flag_status_subaction_is_forwarded(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="grnt-status", name="Granted")
        self._grant("feature_flag", str(flag.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.pk}/status/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_feature_flag_status_subaction_is_deflected(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="hidd-status", name="Hidden")
        res = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.pk}/status/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_feature_flag_dependent_flags_subaction_is_forwarded(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="grnt-dep", name="Granted")
        self._grant("feature_flag", str(flag.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.pk}/dependent_flags/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_survey_archived_response_uuids_is_forwarded(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Granted survey")
        self._grant("survey", str(survey.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/surveys/{survey.pk}/archived-response-uuids/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_survey_archived_response_uuids_is_deflected(self) -> None:
        survey = Survey.objects.create(team=self.team, name="Hidden survey")
        res = self.client.get(f"/api/projects/{self.team.pk}/surveys/{survey.pk}/archived-response-uuids/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_session_recording_snapshots_is_forwarded(self) -> None:
        session_id = "0195b7c5-1c8a-7000-aaaa-aaaaaaaaaaaa"
        rec = SessionRecording.objects.create(team=self.team, session_id=session_id)
        self._grant("session_recording", str(rec.id))
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_session_recording_snapshots_is_deflected(self) -> None:
        session_id = "0195b7c5-1c8a-7000-bbbb-bbbbbbbbbbbb"
        SessionRecording.objects.create(team=self.team, session_id=session_id)
        res = self.client.get(f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_granted_notebook_kernel_status_is_forwarded(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="K", short_id="KRN00001")
        AccessControl.objects.create(
            team=self.team,
            resource="notebook",
            resource_id=str(notebook.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{notebook.short_id}/kernel/status/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_notebook_kernel_status_is_deflected(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="K", short_id="KRN00002")
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{notebook.short_id}/kernel/status/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_insight_list_filtered_by_short_id_is_forwarded_when_granted(self) -> None:
        # The async-refresh path on saved insights resolves by `?short_id=`. The cascade
        # writes an insight AC row for each ph-query SavedInsightNode embedded in a
        # granted notebook; this rule lets the URL pass once that AC row exists.
        from posthog.models.insight import Insight

        insight = Insight.objects.create(team=self.team, name="Granted insight", short_id="INS00099")
        self._grant("insight", str(insight.pk))
        res = self.client.get(f"/api/projects/{self.team.pk}/insights/?short_id={insight.short_id}")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_insight_list_filtered_by_ungranted_short_id_is_deflected(self) -> None:
        from posthog.models.insight import Insight

        insight = Insight.objects.create(team=self.team, name="Hidden insight", short_id="INS00098")
        res = self.client.get(f"/api/projects/{self.team.pk}/insights/?short_id={insight.short_id}")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_insight_list_without_short_id_is_deflected(self) -> None:
        # Bare insight list (no `short_id` filter) would enumerate; deflected.
        res = self.client.get(f"/api/projects/{self.team.pk}/insights/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand([("comments/",), ("comments/count/",)])
    def test_comments_with_granted_notebook_scope_is_forwarded(self, path: str) -> None:
        notebook = Notebook.objects.create(team=self.team, title="N", short_id="CMT00001")
        AccessControl.objects.create(
            team=self.team,
            resource="notebook",
            resource_id=str(notebook.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        res = self.client.get(f"/api/projects/{self.team.pk}/{path}?scope=Notebook&item_id={notebook.short_id}")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_comments_with_ungranted_notebook_scope_is_deflected(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="N", short_id="CMT00002")
        res = self.client.get(f"/api/projects/{self.team.pk}/comments/?scope=Notebook&item_id={notebook.short_id}")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_comments_with_replay_scope_for_granted_recording_is_forwarded(self) -> None:
        session_id = "0195b7c5-1c8a-7000-cccc-cccccccccccc"
        rec = SessionRecording.objects.create(team=self.team, session_id=session_id)
        self._grant("session_recording", str(rec.id))
        res = self.client.get(f"/api/projects/{self.team.pk}/comments/?scope=Replay&item_id={session_id}")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_comments_without_scope_is_deflected(self) -> None:
        # Without scope+item_id we can't bind to a granted resource → deflect.
        res = self.client.get(f"/api/projects/{self.team.pk}/comments/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_comments_with_unknown_scope_is_deflected(self) -> None:
        res = self.client.get(f"/api/projects/{self.team.pk}/comments/?scope=NoSuchThing&item_id=anything")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("default_release_conditions", "environments"),
            ("default_evaluation_contexts", "environments"),
            ("experiments/stats", "projects"),
            ("experiments/eligible_feature_flags", "projects"),
            ("experiment_holdouts", "projects"),
            ("experiment_saved_metrics", "projects"),
            ("notebooks/recording_comments", "projects"),
        ]
    )
    def test_metadata_endpoint_requires_any_grant(self, endpoint: str, scope: str) -> None:
        # Verify rule routing only — not the underlying viewset's response semantics.
        # Without any grant the URL is 404'd by middleware before the viewset runs.
        # With a notebook AC row in place, the middleware forwards; the response code
        # then depends on the viewset (200, 400 for missing args, etc.) but is never
        # the middleware's 404.
        url_no_grant = f"/api/{scope}/{self.team.pk}/{endpoint}/"
        res_no_grant = self.client.get(url_no_grant)
        self.assertEqual(res_no_grant.status_code, status.HTTP_404_NOT_FOUND)

        notebook = Notebook.objects.create(
            team=self.team, title="N", short_id=f"MD{abs(hash(endpoint)) % 100000:05d}"[:8]
        )
        AccessControl.objects.create(
            team=self.team,
            resource="notebook",
            resource_id=str(notebook.pk),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        res_with_grant = self.client.get(url_no_grant)
        # Middleware no longer 404s — the viewset may return its own status (e.g. 200,
        # 400 for missing query params, 403 from the AC layer if the resource isn't
        # one the AC layer enables for guests). Anything other than middleware's 404
        # means the rule passed.
        # A 404 from the viewset itself (NotFound on a missing detail) is not what we
        # test for here; if the URL is registered on this scope, middleware passing it
        # results in some 2xx/4xx other than 404 (or a 404 raised after middleware).
        # We check for the absence of the specific JsonResponse middleware emits.
        self.assertNotEqual(
            res_with_grant.content,
            b'{"detail": "Not found."}',
            f"middleware 404'd {endpoint}; expected forward",
        )
