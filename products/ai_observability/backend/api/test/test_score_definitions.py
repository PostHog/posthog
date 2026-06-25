from posthog.test.base import APIBaseTest
from unittest.mock import ANY, patch

from parameterized import parameterized
from rest_framework import status

from products.ai_observability.backend.models.score_definitions import (
    ScoreDefinition,
    ScoreDefinitionVersion,
    StaleScoreDefinitionVersion,
)


class TestScoreDefinitionsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.ai_observability.backend.api.score_definitions.feature_enabled_or_false", return_value=True
        )
        self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)

    def _endpoint(self) -> str:
        return f"/api/environments/{self.team.id}/llm_analytics/score_definitions/"

    def _current_version(self, definition: ScoreDefinition) -> ScoreDefinitionVersion:
        current_version = definition.current_version
        assert current_version is not None
        return current_version

    @parameterized.expand(
        [
            (
                "categorical_single",
                {
                    "name": "Quality",
                    "kind": "categorical",
                    "config": {
                        "options": [
                            {"key": "good", "label": "Good"},
                            {"key": "bad", "label": "Bad"},
                        ]
                    },
                },
            ),
            (
                "categorical_multiple",
                {
                    "name": "Themes",
                    "kind": "categorical",
                    "config": {
                        "options": [
                            {"key": "helpful", "label": "Helpful"},
                            {"key": "accurate", "label": "Accurate"},
                            {"key": "complete", "label": "Complete"},
                        ],
                        "selection_mode": "multiple",
                        "min_selections": 1,
                        "max_selections": 2,
                    },
                },
            ),
            (
                "numeric",
                {
                    "name": "Score",
                    "kind": "numeric",
                    "config": {"min": 0, "max": 5, "step": 1},
                },
            ),
            (
                "boolean",
                {
                    "name": "Resolved",
                    "kind": "boolean",
                    "config": {"true_label": "Yes", "false_label": "No"},
                },
            ),
        ]
    )
    def test_can_create_score_definitions_for_all_supported_kinds(self, _name: str, payload: dict):
        response = self.client.post(self._endpoint(), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        current_version = self._current_version(definition)
        self.assertEqual(definition.created_by, self.user)
        self.assertEqual(definition.kind, payload["kind"])
        self.assertEqual(current_version.version, 1)
        self.assertEqual(current_version.config, payload["config"])

    def test_patch_updates_metadata_without_creating_a_new_version(self):
        definition = self._create_definition()

        response = self.client.patch(
            f"{self._endpoint()}{definition.id}/",
            {"name": "Updated quality", "description": "Updated description", "archived": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()
        current_version = self._current_version(definition)
        self.assertEqual(definition.name, "Updated quality")
        self.assertEqual(definition.description, "Updated description")
        self.assertTrue(definition.archived)
        self.assertEqual(current_version.version, 1)
        self.assertEqual(definition.versions.count(), 1)

    def test_create_starts_active(self):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Customer Satisfaction",
                "kind": "boolean",
                "config": {"true_label": "Good", "false_label": "Bad"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        self.assertFalse(definition.archived)

    @parameterized.expand(
        [
            (
                "numeric_with_categorical_keys",
                "numeric",
                {"options": [{"key": "a", "label": "A"}]},
            ),
            (
                "boolean_with_numeric_keys",
                "boolean",
                {"min": 0, "max": 1},
            ),
            (
                "categorical_with_boolean_keys",
                "categorical",
                {"true_label": "Yes", "false_label": "No"},
            ),
        ]
    )
    def test_create_rejects_config_keys_that_do_not_match_kind(self, _name: str, kind: str, config: dict):
        response = self.client.post(
            self._endpoint(),
            {"name": "Mismatch", "kind": kind, "config": config},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "config")
        self.assertIn("Unsupported keys", response.data["detail"])

    def test_response_exposes_current_version_id(self):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "bad", "label": "Bad"},
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        self.assertEqual(response.data["current_version"], 1)
        self.assertEqual(response.data["current_version_id"], str(definition.current_version_id))

    def test_create_rejects_archived_scorers(self):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Customer Satisfaction",
                "kind": "boolean",
                "archived": True,
                "config": {"true_label": "Good", "false_label": "Bad"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "archived")
        self.assertEqual(response.data["detail"], "New scorers must be created as active.")

    @patch("products.ai_observability.backend.api.score_definitions.report_user_action")
    def test_create_reports_user_action(self, mock_report_user_action):
        response = self.client.post(
            self._endpoint(),
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "bad", "label": "Bad"},
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])

        mock_report_user_action.assert_called_once_with(
            self.user,
            "llma scorer created",
            {
                "scorer_id": str(definition.id),
                "scorer_name": "Quality",
                "scorer_kind": "categorical",
                "has_description": False,
                "archived": False,
                "version": 1,
            },
            team=self.team,
            request=ANY,
        )

    def test_new_version_creates_immutable_snapshot_and_advances_current_version(self):
        definition = self._create_definition()
        original_config = self._current_version(definition).config

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "config": {
                    "options": [
                        {"key": "pass", "label": "Pass"},
                        {"key": "needs_work", "label": "Needs work"},
                        {"key": "fail", "label": "Fail"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 1,
                    "max_selections": 2,
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()
        current_version = self._current_version(definition)
        self.assertEqual(current_version.version, 2)
        self.assertEqual(definition.versions.count(), 2)
        self.assertEqual(definition.versions.get(version=1).config, original_config)
        self.assertEqual(
            definition.versions.get(version=2).config,
            {
                "options": [
                    {"key": "pass", "label": "Pass"},
                    {"key": "needs_work", "label": "Needs work"},
                    {"key": "fail", "label": "Fail"},
                ],
                "selection_mode": "multiple",
                "min_selections": 1,
                "max_selections": 2,
            },
        )

    def test_new_version_with_matching_base_version_advances_to_v2(self):
        definition = self._create_definition()

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "base_version": 1,
                "config": {
                    "options": [
                        {"key": "pass", "label": "Pass"},
                        {"key": "fail", "label": "Fail"},
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()
        self.assertEqual(self._current_version(definition).version, 2)

    def test_create_new_version_raises_when_base_version_is_stale_at_lock_time(self):
        """Lower-level guarantee: the base_version check happens inside `select_for_update`.

        A regression that moves the check above the lock would let two concurrent writers with the
        same `base_version` both pass — exactly what OCC must prevent. Asserting the model contract
        here keeps that fix in place even if the view layer changes.
        """
        definition = self._create_definition()
        # Another writer advances the scorer to v2 — equivalent to "the row was bumped between when
        # the caller observed v1 and when the caller's transaction acquired the lock".
        definition.create_new_version(
            config={"options": [{"key": "winner", "label": "Winner"}]},
            created_by=self.user,
        )

        with self.assertRaises(StaleScoreDefinitionVersion) as cm:
            definition.create_new_version(
                config={"options": [{"key": "loser", "label": "Loser"}]},
                created_by=self.user,
                base_version=1,
            )

        self.assertEqual(cm.exception.current_version, 2)
        # No third version was created.
        self.assertEqual(ScoreDefinitionVersion.objects.filter(definition=definition).count(), 2)

    def test_new_version_with_stale_base_version_returns_409(self):
        definition = self._create_definition()
        # Someone else bumps the scorer to v2 first.
        definition.create_new_version(
            config={"options": [{"key": "intermediate", "label": "Intermediate"}]},
            created_by=self.user,
        )

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "base_version": 1,
                "config": {
                    "options": [
                        {"key": "stale", "label": "Stale"},
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["current_version"], 2)
        definition.refresh_from_db()
        # Scorer still at v2 — the stale request did not bump it.
        self.assertEqual(self._current_version(definition).version, 2)

    @parameterized.expand(
        [
            ("smuggle_boolean_kind_with_boolean_config", "categorical", "boolean", {"true_label": "Yes"}),
            ("smuggle_numeric_kind_with_numeric_config", "categorical", "numeric", {"min": 0, "max": 1}),
            (
                "smuggle_categorical_kind_with_categorical_config",
                "boolean",
                "categorical",
                {"options": [{"key": "a", "label": "A"}]},
            ),
        ]
    )
    def test_new_version_ignores_kind_smuggled_in_body(
        self, _name: str, scorer_kind: str, smuggled_kind: str, config: dict
    ):
        definition = self._create_definition(kind=scorer_kind)

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {"kind": smuggled_kind, "config": config},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "config")
        self.assertIn("Unsupported keys", response.data["detail"])
        definition.refresh_from_db()
        self.assertEqual(self._current_version(definition).version, 1)

    # The /new_version/ custom @action has to declare required_scopes explicitly;
    # without it the default scope resolver returns None for non-CRUD action names and PAK
    # requests are rejected with "This action does not support personal API key access".
    @parameterized.expand(
        [
            ("write_scope_allowed", ["llm_analytics:write"], status.HTTP_200_OK),
            ("read_scope_denied", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
            ("wrong_scope_denied", ["insight:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_new_version_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        definition = self._create_definition()
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "config": {
                    "options": [
                        {"key": "pak-pass", "label": "Pass"},
                    ]
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, expected_status)

    def test_list_defaults_to_active_only_and_respects_archived_param(self):
        active = self._create_definition(name="Active scorer", kind="categorical")
        archived = self._create_definition(name="Archived scorer", kind="categorical", archived=True)

        # Default — no archived param → active only
        response = self.client.get(self._endpoint())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [result["id"] for result in response.data["results"]]
        self.assertIn(str(active.id), ids)
        self.assertNotIn(str(archived.id), ids)

        # archived=false → active only (same as default)
        response = self.client.get(self._endpoint(), {"archived": "false"})
        ids = [result["id"] for result in response.data["results"]]
        self.assertIn(str(active.id), ids)
        self.assertNotIn(str(archived.id), ids)

        # archived=true → archived only
        response = self.client.get(self._endpoint(), {"archived": "true"})
        ids = [result["id"] for result in response.data["results"]]
        self.assertNotIn(str(active.id), ids)
        self.assertIn(str(archived.id), ids)

    @parameterized.expand([("empty", ""), ("whitespace", "   "), ("unparseable", "invalid")])
    def test_list_treats_non_boolean_archived_param_as_default_active_only(self, _name: str, value: str):
        active = self._create_definition(name="Active scorer", kind="categorical")
        archived = self._create_definition(name="Archived scorer", kind="categorical", archived=True)

        response = self.client.get(self._endpoint(), {"archived": value})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [result["id"] for result in response.data["results"]]
        self.assertIn(str(active.id), ids)
        self.assertNotIn(str(archived.id), ids)

    def test_list_supports_search_kind_archived_and_ordering(self):
        active = self._create_definition(name="Quality", kind="categorical")
        archived = self._create_definition(
            name="Resolved",
            kind="boolean",
            archived=True,
        )

        response = self.client.get(
            self._endpoint(),
            {
                "search": "resolved",
                "kind": "boolean",
                "archived": "true",
                "order_by": "name",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([result["id"] for result in response.data["results"]], [str(archived.id)])
        self.assertNotIn(str(active.id), [result["id"] for result in response.data["results"]])

    @patch("products.ai_observability.backend.api.score_definitions.report_user_action")
    def test_patch_reports_user_action(self, mock_report_user_action):
        definition = self._create_definition()
        mock_report_user_action.reset_mock()

        response = self.client.patch(
            f"{self._endpoint()}{definition.id}/",
            {"name": "Updated quality", "description": "Updated description", "archived": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()

        mock_report_user_action.assert_called_once_with(
            self.user,
            "llma scorer updated",
            {
                "scorer_id": str(definition.id),
                "scorer_name": "Updated quality",
                "scorer_kind": "categorical",
                "has_description": True,
                "archived": True,
                "version": 1,
                "changed_fields": ["name", "description", "archived"],
                "archived_new_value": True,
            },
            team=self.team,
            request=ANY,
        )

    @patch("products.ai_observability.backend.api.score_definitions.report_user_action")
    def test_new_version_reports_user_action(self, mock_report_user_action):
        definition = self._create_definition()
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"{self._endpoint()}{definition.id}/new_version/",
            {
                "config": {
                    "options": [
                        {"key": "pass", "label": "Pass"},
                        {"key": "fail", "label": "Fail"},
                    ]
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        definition.refresh_from_db()

        mock_report_user_action.assert_called_once_with(
            self.user,
            "llma scorer version created",
            {
                "scorer_id": str(definition.id),
                "scorer_name": definition.name,
                "scorer_kind": definition.kind,
                "has_description": False,
                "archived": False,
                "version": 2,
            },
            team=self.team,
            request=ANY,
        )

    def _default_config_for_kind(self, kind: str) -> dict:
        if kind == "categorical":
            return {
                "options": [
                    {"key": "good", "label": "Good"},
                    {"key": "bad", "label": "Bad"},
                ]
            }
        if kind == "numeric":
            return {"min": 0, "max": 1, "step": 0.1}
        if kind == "boolean":
            return {"true_label": "Yes", "false_label": "No"}
        raise ValueError(f"Unsupported kind: {kind}")

    def _create_definition(
        self,
        *,
        name: str = "Quality",
        kind: str = "categorical",
        archived: bool = False,
        config: dict | None = None,
    ) -> ScoreDefinition:
        payload = {
            "name": name,
            "kind": kind,
            "config": config or self._default_config_for_kind(kind),
        }
        response = self.client.post(self._endpoint(), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        definition = ScoreDefinition.objects.get(pk=response.data["id"])
        if archived:
            definition.archived = True
            definition.save(update_fields=["archived", "updated_at"])
        return definition
