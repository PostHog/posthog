from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.team import TEAM_CONFIG_FIELDS
from posthog.models.organization import OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.team import Team

from products.dashboards.backend.models.dashboard import Dashboard

# Adversarial differential parity harness.
#
# /api/environments/{id}/ (Team) and /api/projects/{id}/ (Project) address the SAME underlying entity because
# Project ↔ Team is 1:1 and share the same numeric id. This suite makes real HTTP calls to BOTH and asserts the
# responses (and resulting DB state for writes) are identical. Any divergence fails — there is no "probably fine".
#
# Fields a client legitimately sees on /api/projects/ but not /api/environments/ — both are project-only on
# master (product_description is a Project concept; is_pending_deletion was added project-side). Extra fields on
# the redirect target are safe. Everything else must match exactly.
PROJECT_ONLY_DETAIL_FIELDS = {"product_description", "is_pending_deletion"}

# Read-only fields whose VALUE legitimately differs but is semantically equivalent, so byte-equality is not
# required (only presence + non-null). Currently just `created_at`: /api/environments/ returns Team.created_at
# and /api/projects/ returns Project.created_at — two rows created milliseconds apart in the same transaction.
# This is pre-existing /api/projects/ behavior (created_at is not a passthrough field) and is read-only, so it
# cannot break a client. Everything else must be byte-identical.
READ_ONLY_NEAR_EQUIVALENT_FIELDS = {"created_at"}


class DifferentialParityBase(APIBaseTest):
    # Allow replica + persons DB queries (personal API key auth, group types) so every code path runs locally.
    # "__all__" is Django's documented sentinel for "every configured database"; the base type is set[str].
    databases = "__all__"  # type: ignore[assignment]

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        # Sanity: the two endpoints must address the same entity.
        assert self.project.id == self.team.id, "Project/Team id mismatch breaks the differential assumption"

    def env_url(self, suffix: str = "") -> str:
        return f"/api/environments/{self.team.id}/{suffix}"

    def project_url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.project.id}/{suffix}"

    def assert_bodies_equal(self, env_body: Any, proj_body: Any, *, allow_project_only: set[str] | None = None) -> None:
        allow_project_only = allow_project_only or set()
        if isinstance(env_body, dict) and isinstance(proj_body, dict):
            env_keys, proj_keys = set(env_body), set(proj_body)
            self.assertEqual(
                env_keys - proj_keys, set(), f"keys only on /api/environments/: {sorted(env_keys - proj_keys)}"
            )
            self.assertEqual(
                proj_keys - env_keys,
                allow_project_only,
                f"unexpected keys only on /api/projects/: {sorted((proj_keys - env_keys) - allow_project_only)}",
            )
            for key in env_keys:
                if key in READ_ONLY_NEAR_EQUIVALENT_FIELDS:
                    # Value may differ (different row), but both must be present and non-null.
                    self.assertIsNotNone(env_body[key], f"env '{key}' unexpectedly null")
                    self.assertIsNotNone(proj_body[key], f"project '{key}' unexpectedly null")
                    continue
                self.assertEqual(
                    env_body[key],
                    proj_body[key],
                    f"field '{key}' diverges: env={env_body[key]!r} project={proj_body[key]!r}",
                )
        else:
            self.assertEqual(env_body, proj_body)


class TestReadParity(DifferentialParityBase):
    def test_get_detail_parity(self):
        env = self.client.get(self.env_url())
        proj = self.client.get(self.project_url())
        self.assertEqual(env.status_code, status.HTTP_200_OK, env.json())
        self.assertEqual(proj.status_code, status.HTTP_200_OK, proj.json())
        self.assert_bodies_equal(env.json(), proj.json(), allow_project_only=PROJECT_ONLY_DETAIL_FIELDS)

    def test_list_parity(self):
        env = self.client.get("/api/environments/")
        proj = self.client.get("/api/projects/")
        self.assertEqual(env.status_code, status.HTTP_200_OK, env.json())
        self.assertEqual(proj.status_code, status.HTTP_200_OK, proj.json())
        env_results = {r["id"]: r for r in env.json()["results"]}
        proj_results = {r["id"]: r for r in proj.json()["results"]}
        self.assertEqual(set(env_results), set(proj_results), "different ids listed")
        for team_id, env_row in env_results.items():
            self.assert_bodies_equal(env_row, proj_results[team_id])

    def test_is_generating_demo_data_parity(self):
        env = self.client.get(self.env_url("is_generating_demo_data/"))
        proj = self.client.get(self.project_url("is_generating_demo_data/"))
        self.assertEqual(env.status_code, proj.status_code)
        self.assert_bodies_equal(env.json(), proj.json())

    def test_activity_parity(self):
        env = self.client.get(self.env_url("activity/"))
        proj = self.client.get(self.project_url("activity/"))
        self.assertEqual(env.status_code, proj.status_code)
        self.assert_bodies_equal(env.json(), proj.json())

    def test_default_release_conditions_get_parity(self):
        env = self.client.get(self.env_url("default_release_conditions/"))
        proj = self.client.get(self.project_url("default_release_conditions/"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())

    def test_experiments_config_get_parity(self):
        env = self.client.get(self.env_url("experiments_config/"))
        proj = self.client.get(self.project_url("experiments_config/"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())

    def test_logs_config_get_parity(self):
        env = self.client.get(self.env_url("logs_config/"))
        proj = self.client.get(self.project_url("logs_config/"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())

    def test_default_evaluation_contexts_get_parity(self):
        env = self.client.get(self.env_url("default_evaluation_contexts/"))
        proj = self.client.get(self.project_url("default_evaluation_contexts/"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())

    def test_event_ingestion_restrictions_get_parity(self):
        env = self.client.get(self.env_url("event_ingestion_restrictions/"))
        proj = self.client.get(self.project_url("event_ingestion_restrictions/"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())

    def test_settings_as_of_scoped_parity(self):
        qs = "?at=2020-01-01T00:00:00Z&scope=timezone&scope=session_recording_opt_in"
        env = self.client.get(self.env_url(f"settings_as_of/{qs}"))
        proj = self.client.get(self.project_url(f"settings_as_of/{qs}"))
        self.assertEqual(env.status_code, proj.status_code, (env.json(), proj.json()))
        self.assert_bodies_equal(env.json(), proj.json())


# A representative valid value for every config field. We deliberately require an entry for EVERY field in
# TEAM_CONFIG_FIELDS (see test below) so a newly added config field cannot slip through untested. The value
# need not be "correct" — if the input is rejected, the test simply asserts both endpoints reject it identically.
FIELD_VALUES: dict[str, Any] = {
    "app_urls": ["https://example.com"],
    "anonymize_ips": True,
    "completed_snippet_onboarding": True,
    "test_account_filters": [],
    "test_account_filters_default_checked": True,
    "path_cleaning_filters": [],
    "is_demo": True,
    "timezone": "America/New_York",
    "data_attributes": ["data-attr"],
    "person_display_name_properties": ["email"],
    "correlation_config": {"excluded_person_property_names": ["foo"]},
    "autocapture_opt_out": True,
    "autocapture_exceptions_opt_in": True,
    "autocapture_web_vitals_opt_in": True,
    "autocapture_web_vitals_allowed_metrics": ["FCP"],
    "autocapture_exceptions_errors_to_ignore": ["err"],
    "capture_console_log_opt_in": True,
    "logs_settings": {"retention_days": 30},
    "capture_performance_opt_in": True,
    "session_recording_opt_in": True,
    "session_recording_sample_rate": "0.50",
    "session_recording_minimum_duration_milliseconds": 1000,
    "session_recording_linked_flag": {"id": 1, "key": "flag"},
    "session_recording_network_payload_capture_config": {"recordHeaders": True},
    "session_recording_masking_config": {"maskAllInputs": True},
    "session_recording_url_trigger_config": [],
    "session_recording_url_blocklist_config": [],
    "session_recording_event_trigger_config": [],
    "session_recording_trigger_match_type_config": "all",
    "session_recording_trigger_groups": {"version": 2, "groups": []},
    "session_recording_retention_period": "30d",
    "session_replay_config": {"record_canvas": True},
    "survey_config": {"appearance": {"backgroundColor": "#ffffff"}},
    "week_start_day": 1,
    "primary_dashboard": "__PER_TWIN_DASHBOARD__",  # special-cased: a dashboard belonging to each twin
    "live_events_columns": ["event"],
    "recording_domains": ["https://example.com"],
    "cookieless_server_hash_mode": 1,
    "human_friendly_comparison_periods": True,
    "inject_web_apps": True,
    "extra_settings": {"foo": "bar"},
    "modifiers": {"bounceRateDurationSeconds": 30},
    "has_completed_onboarding_for": {"1": True},
    "surveys_opt_in": True,
    "heatmaps_opt_in": True,
    "flags_persistence_default": True,
    "feature_flag_confirmation_enabled": True,
    "feature_flag_confirmation_message": "Are you sure?",
    "default_evaluation_contexts_enabled": True,
    "require_evaluation_contexts": True,
    "capture_dead_clicks": True,
    "default_data_theme": 1,
    "revenue_analytics_config": {"filter_test_accounts": True},
    "marketing_analytics_config": {"attribution_window_days": 14},
    "customer_analytics_config": {"activity_event": "$pageview"},
    "workflows_config": {"capture_workflows_engagement_events": True},
    "onboarding_tasks": {"task_x": "completed"},
    "base_currency": "EUR",
    "web_analytics_pre_aggregated_tables_enabled": True,
    "receive_org_level_activity_logs": True,
    "business_model": "B2B",
    "conversations_enabled": True,
    "conversations_settings": {"widget_greeting_text": "hi"},
    "proactive_tasks_enabled": True,
}


class TestWriteParity(DifferentialParityBase):
    def _make_twin(self) -> tuple[Project, Team]:
        project, team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        return project, team

    def test_every_config_field_has_a_test_value(self):
        # Completeness guard: every writable config field MUST be exercised by the matrix below.
        missing = set(TEAM_CONFIG_FIELDS) - set(FIELD_VALUES)
        self.assertEqual(missing, set(), f"Config fields with no differential test value: {sorted(missing)}")

    @parameterized.expand(sorted(TEAM_CONFIG_FIELDS))
    def test_write_field_parity(self, field: str):
        project_a, team_a = self._make_twin()
        project_b, team_b = self._make_twin()

        value = FIELD_VALUES[field]
        if field == "primary_dashboard":
            dash_a = Dashboard.objects.create(team=team_a, name="d")
            dash_b = Dashboard.objects.create(team=team_b, name="d")
            body_a: dict[str, Any] = {field: dash_a.id}
            body_b: dict[str, Any] = {field: dash_b.id}
        else:
            body_a = {field: value}
            body_b = {field: value}

        resp_a = self.client.patch(f"/api/environments/{team_a.id}/", body_a, format="json")
        resp_b = self.client.patch(f"/api/projects/{project_b.id}/", body_b, format="json")

        # 1. Accept/reject parity: both endpoints must agree on the HTTP status for the same input.
        self.assertEqual(
            resp_a.status_code,
            resp_b.status_code,
            f"status diverges for '{field}': env={resp_a.status_code} ({resp_a.json()}) "
            f"project={resp_b.status_code} ({resp_b.json()})",
        )

        if resp_a.status_code == status.HTTP_200_OK:
            # 2. Round-trip parity: reading the field back must yield the same result via both routes.
            get_a = self.client.get(f"/api/environments/{team_a.id}/").json()
            get_b = self.client.get(f"/api/projects/{project_b.id}/").json()
            if field == "primary_dashboard":
                self.assertEqual(get_a[field], dash_a.id)
                self.assertEqual(get_b[field], dash_b.id)
            else:
                self.assertEqual(
                    get_a[field],
                    get_b[field],
                    f"round-trip value diverges for '{field}': env={get_a[field]!r} project={get_b[field]!r}",
                )
        else:
            # 3. Error parity: same rejection body for the same bad input.
            self.assertEqual(
                resp_a.json(),
                resp_b.json(),
                f"error body diverges for '{field}'",
            )


# Identity/random-per-row fields that legitimately differ between two distinct twin entities. Excluded when
# comparing team-shaped action responses; everything else must match.
TEAM_SHAPED_VOLATILE_FIELDS = {
    "id",
    "project_id",
    "uuid",
    "api_token",
    "secret_api_token",
    "secret_api_token_backup",
    "live_events_token",
    "created_at",
    "updated_at",
    "conversations_settings",  # holds a randomly generated widget token
    "test_account_filters",  # default value references each twin's own auto-created "internal users" cohort id
    "primary_dashboard",  # each twin auto-creates its own default primary dashboard (distinct row id)
    "product_intents",  # list of rows with per-row timestamps; compared structurally in the intent tests instead
    "product_description",  # project-only
    "is_pending_deletion",  # project-only (added project-side on master)
}


def _normalize_intents(intents: list[dict]) -> list[dict]:
    """Drop per-row timestamps so two twins' product_intents can be compared structurally."""
    keep = {"product_type"}
    return sorted(
        (
            {**{k: v for k, v in i.items() if k in keep}, "onboarded": i.get("onboarding_completed_at") is not None}
            for i in intents
        ),
        key=lambda i: i["product_type"],
    )


# Write-action parity cases: (name, http_method, url_suffix, body, expected_status, compare_mode).
# compare_mode: "team_shaped" → response is the serialized team (compare minus volatile fields);
#               "team_shaped_intents" → also compare product_intents structurally; "full_body" → exact body match.
# Adding a new environment action that mirrors onto projects is a single row here. The only action NOT in this
# table is default_evaluation_contexts, which is an irreducible POST-then-DELETE sequence (separate test below).
WRITE_ACTION_CASES = [
    ("reset_token", "patch", "reset_token/", None, status.HTTP_200_OK, "team_shaped"),
    ("rotate_secret_token", "patch", "rotate_secret_token/", None, status.HTTP_200_OK, "team_shaped"),
    ("delete_secret_token_backup", "patch", "delete_secret_token_backup/", None, status.HTTP_200_OK, "team_shaped"),
    (
        "generate_conversations_public_token",
        "post",
        "generate_conversations_public_token/",
        None,
        status.HTTP_200_OK,
        "team_shaped",
    ),
    (
        "add_product_intent",
        "patch",
        "add_product_intent/",
        {"product_type": "product_analytics", "metadata": {}},
        status.HTTP_201_CREATED,
        "team_shaped_intents",
    ),
    (
        "complete_product_onboarding",
        "patch",
        "complete_product_onboarding/",
        {"product_type": "product_analytics", "metadata": {}},
        status.HTTP_200_OK,
        "team_shaped_intents",
    ),
    (
        "logs_config",
        "patch",
        "logs_config/",
        {"logs_distinct_id_attribute_key": "myDistinctId"},
        status.HTTP_200_OK,
        "full_body",
    ),
    (
        "default_release_conditions",
        "put",
        "default_release_conditions/",
        {"enabled": True, "default_groups": [{"properties": [], "rollout_percentage": 50}]},
        status.HTTP_200_OK,
        "full_body",
    ),
    (
        "experiments_config",
        "patch",
        "experiments_config/",
        {"default_experiment_stats_method": "bayesian"},
        status.HTTP_200_OK,
        "full_body",
    ),
]


class TestWriteActionParity(DifferentialParityBase):
    def _make_twin(self) -> tuple[Project, Team]:
        project, team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        return project, team

    def _assert_team_shaped_parity(self, body_a: dict, body_b: dict) -> None:
        a = {k: v for k, v in body_a.items() if k not in TEAM_SHAPED_VOLATILE_FIELDS}
        b = {k: v for k, v in body_b.items() if k not in TEAM_SHAPED_VOLATILE_FIELDS}
        self.assertEqual(set(a), set(b), "team-shaped action response key sets diverge")
        for key in a:
            self.assertEqual(
                a[key], b[key], f"action response field '{key}' diverges: env={a[key]!r} project={b[key]!r}"
            )

    def _run_twin_action(self, method: str, suffix: str, body: dict | None = None) -> tuple[Any, Any]:
        project_a, team_a = self._make_twin()
        project_b, team_b = self._make_twin()
        call = getattr(self.client, method)
        kwargs = {"format": "json"} if body is not None else {}
        resp_a = call(f"/api/environments/{team_a.id}/{suffix}", body or None, **kwargs)
        resp_b = call(f"/api/projects/{project_b.id}/{suffix}", body or None, **kwargs)
        self.assertEqual(
            resp_a.status_code,
            resp_b.status_code,
            f"status diverges for {method.upper()} {suffix}: env={resp_a.status_code} project={resp_b.status_code} "
            f"({resp_a.content!r} vs {resp_b.content!r})",
        )
        return resp_a, resp_b

    @parameterized.expand(WRITE_ACTION_CASES)
    def test_write_action_parity(self, name, method, suffix, body, expected_status, compare):
        resp_a, resp_b = self._run_twin_action(method, suffix, body)
        self.assertEqual(resp_a.status_code, expected_status, resp_a.json())
        if compare == "full_body":
            self.assertEqual(resp_a.json(), resp_b.json())
            return
        self._assert_team_shaped_parity(resp_a.json(), resp_b.json())
        if compare == "team_shaped_intents":
            self.assertEqual(
                _normalize_intents(resp_a.json()["product_intents"]),
                _normalize_intents(resp_b.json()["product_intents"]),
            )

    def test_default_evaluation_contexts_post_and_delete_parity(self):
        # POST returns a per-row id (differs between twins); compare everything else.
        post_body = {"context_name": "production"}
        resp_a, resp_b = self._run_twin_action("post", "default_evaluation_contexts/", post_body)
        self.assertEqual(resp_a.status_code, status.HTTP_200_OK, resp_a.json())
        a = {k: v for k, v in resp_a.json().items() if k != "id"}
        b = {k: v for k, v in resp_b.json().items() if k != "id"}
        self.assertEqual(a, b)

        # DELETE on fresh twins for status + body parity.
        del_body = {"context_name": "production"}
        resp_a2, resp_b2 = self._run_twin_action("delete", "default_evaluation_contexts/", del_body)
        self.assertEqual(resp_a2.json(), resp_b2.json())


# NOTE on personal-API-key scope parity: both viewsets share identical scope logic
# (dangerously_get_required_scopes is mirrored, and APIScopePermission is the same), and the existing
# rewrite-client factory suite (test_project.py vs test_team.py) exercises read-only/write key behavior against
# BOTH surfaces on CI. It is intentionally NOT duplicated here: personal-API-key auth reads the `replica`
# connection, which cannot see a key written inside the test's transaction on a standard TestCase, so any such
# assertion is unrunnable locally regardless of endpoint. That dimension is covered on CI by the factory suite.


class TestLifecycleMethodDivergences(DifferentialParityBase):
    """CREATE and DELETE are the ONLY methods that intentionally differ between the two surfaces. Both
    differences pre-date this change and are deliberate. These tests pin the current behavior so it cannot
    change silently, and so the env→project redirect decision is made with full awareness of them."""

    def _make_twin(self) -> tuple[Project, Team]:
        project, team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        return project, team

    def test_create_divergence_env_blocked_project_allowed(self):
        # Top-level environment creation is disabled (multiple environments per project were rolled back), so no
        # client can currently create via /api/environments/. /api/projects/ create works. The redirect therefore
        # does not need to preserve env-create — there is nothing to preserve.
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}
        ]
        self.organization.save()
        env = self.client.post("/api/environments/", {"name": "x"}, format="json")
        proj = self.client.post("/api/projects/", {"name": "x"}, format="json")
        self.assertEqual(env.status_code, status.HTTP_400_BAD_REQUEST, env.json())
        self.assertEqual(proj.status_code, status.HTTP_201_CREATED, proj.json())

    @patch("posthog.api.project.delete_project_data_and_notify_task")
    @patch("posthog.tasks.tasks.delete_project_data_and_notify_task")
    def test_delete_common_case_parity_but_project_is_a_superset(self, mock_team_task, mock_project_task):
        project_a, team_a = self._make_twin()
        project_b, team_b = self._make_twin()

        env = self.client.delete(f"/api/environments/{team_a.id}/")
        proj = self.client.delete(f"/api/projects/{project_b.id}/")

        # Common case (non-cloud, not the last project): both succeed with 204.
        self.assertEqual(env.status_code, status.HTTP_204_NO_CONTENT, env.content)
        self.assertEqual(proj.status_code, status.HTTP_204_NO_CONTENT, proj.content)

        # INTENTIONAL DIVERGENCE (pinned): env deletes a single team (project_id=None); project cascades the
        # whole project (project_id set + all child team_ids) AND additionally enforces a last-project active-
        # subscription guard. In the 1:1 world the data actually removed is equivalent, but post-redirect an
        # env DELETE would inherit the project guard/cascade. This requires explicit product sign-off.
        env_kwargs = mock_team_task.delay.call_args.kwargs
        proj_kwargs = mock_project_task.delay.call_args.kwargs
        self.assertIsNone(env_kwargs["project_id"])
        self.assertEqual(proj_kwargs["project_id"], project_b.id)
        self.assertEqual(env_kwargs["team_ids"], [team_a.id])
        self.assertEqual(proj_kwargs["team_ids"], [team_b.id])


class TestPermissionParity(DifferentialParityBase):
    """Permission parity across membership levels.

    The rest of the suite runs as ADMIN. These tests exercise the MEMBER path — where Veria flagged a possible
    divergence (admin-only config fields writable by non-admins via /api/projects/). For the same membership
    level and the same field, both endpoints must return the SAME status: admin-only fields rejected, member
    fields accepted. A mismatch here is a real access-control divergence, not a cosmetic one.
    """

    def _make_twin(self) -> tuple[Project, Team]:
        project, team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        return project, team

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    @parameterized.expand(
        [
            # (name, field, value, is_admin_only)
            ("admin__timezone", "timezone", "America/New_York", True),
            ("admin__require_evaluation_contexts", "require_evaluation_contexts", True, True),
            ("admin__feature_flag_confirmation_enabled", "feature_flag_confirmation_enabled", True, True),
            ("admin__base_currency", "base_currency", "EUR", True),
            ("admin__capture_dead_clicks", "capture_dead_clicks", True, True),
            ("member__session_recording_opt_in", "session_recording_opt_in", True, False),
            ("member__surveys_opt_in", "surveys_opt_in", True, False),
        ]
    )
    def test_member_config_write_permission_parity(self, _name, field, value, is_admin_only):
        self._set_level(OrganizationMembership.Level.MEMBER)
        _, team_a = self._make_twin()
        project_b, _ = self._make_twin()

        resp_a = self.client.patch(f"/api/environments/{team_a.id}/", {field: value}, format="json")
        resp_b = self.client.patch(f"/api/projects/{project_b.id}/", {field: value}, format="json")

        # The core assertion: both endpoints must agree for a member writing this field.
        self.assertEqual(
            resp_a.status_code,
            resp_b.status_code,
            f"member write of '{field}' diverges: env={resp_a.status_code} ({resp_a.content!r}) "
            f"project={resp_b.status_code} ({resp_b.content!r})",
        )
        if is_admin_only:
            self.assertEqual(resp_a.status_code, status.HTTP_403_FORBIDDEN, resp_a.content)
        else:
            self.assertEqual(resp_a.status_code, status.HTTP_200_OK, resp_a.content)

    @parameterized.expand(
        [
            # member hitting each ported action — status must match across endpoints regardless of allow/deny
            ("default_release_conditions", "get", "default_release_conditions/"),
            ("experiments_config", "get", "experiments_config/"),
            ("default_evaluation_contexts", "get", "default_evaluation_contexts/"),
            ("settings_as_of", "get", "settings_as_of/?at=2020-01-01T00:00:00Z&scope=timezone"),
            ("event_ingestion_restrictions", "get", "event_ingestion_restrictions/"),
            ("logs_config", "get", "logs_config/"),
        ]
    )
    def test_member_action_permission_parity(self, _name, method, suffix):
        self._set_level(OrganizationMembership.Level.MEMBER)
        _, team_a = self._make_twin()
        project_b, _ = self._make_twin()
        call = getattr(self.client, method)
        resp_a = call(f"/api/environments/{team_a.id}/{suffix}")
        resp_b = call(f"/api/projects/{project_b.id}/{suffix}")
        self.assertEqual(
            resp_a.status_code,
            resp_b.status_code,
            f"member action '{suffix}' diverges: env={resp_a.status_code} project={resp_b.status_code}",
        )
