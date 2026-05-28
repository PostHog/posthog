from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from products.autoresearch.backend.templates import TEMPLATES, ResolvedTemplate, _fill_population, resolve_template


class TestTemplateDefinitions(TestCase):
    def test_all_five_templates_present(self) -> None:
        self.assertEqual(
            set(TEMPLATES.keys()),
            {
                "likely_active_soon",
                "at_risk_of_inactivity",
                "return_after_first_use",
                "feature_adoption",
                "repeat_key_behavior",
            },
        )

    @parameterized.expand(list(TEMPLATES.keys()))
    def test_template_has_required_fields(self, key: str) -> None:
        t = TEMPLATES[key]
        self.assertTrue(t.display_name)
        self.assertTrue(t.description)
        self.assertGreater(t.default_horizon_days, 0)
        self.assertTrue(t.output_property_prefix)
        self.assertIsInstance(t.training_population_spec, dict)
        self.assertIsInstance(t.inference_population_spec, dict)

    @parameterized.expand(
        [
            ("likely_active_soon", 7, False, True),
            ("at_risk_of_inactivity", 14, False, True),
            ("return_after_first_use", 7, False, True),
            ("feature_adoption", 14, True, False),
            ("repeat_key_behavior", 7, True, False),
        ]
    )
    def test_template_config(
        self,
        key: str,
        expected_horizon: int,
        requires_user_event: bool,
        requires_activity_resolution: bool,
    ) -> None:
        t = TEMPLATES[key]
        self.assertEqual(t.default_horizon_days, expected_horizon)
        self.assertEqual(t.requires_user_event, requires_user_event)
        self.assertEqual(t.requires_activity_resolution, requires_activity_resolution)


class TestFillPopulation(TestCase):
    def test_ever_performed_event_gets_event_key(self) -> None:
        spec = {"kind": "ever_performed_event"}
        result = _fill_population(spec, "my_event")
        self.assertEqual(result, {"kind": "ever_performed_event", "event": "my_event"})

    def test_active_not_performed_target_gets_event_key(self) -> None:
        spec = {"kind": "active_not_performed_target", "active_within_days": 30}
        result = _fill_population(spec, "feature_clicked")
        self.assertEqual(result["event"], "feature_clicked")
        self.assertEqual(result["kind"], "active_not_performed_target")

    def test_performed_event_within_days_unchanged(self) -> None:
        spec = {"kind": "performed_event_within_days", "days": 30}
        result = _fill_population(spec, "$pageview")
        self.assertNotIn("event", result)

    def test_original_spec_not_mutated(self) -> None:
        spec = {"kind": "ever_performed_event"}
        _fill_population(spec, "my_event")
        self.assertNotIn("event", spec)


class TestResolveTemplate(TestCase):
    def _make_team(self) -> MagicMock:
        team = MagicMock()
        team.pk = 1
        return team

    def test_unknown_template_raises(self) -> None:
        with self.assertRaises(ValueError, msg="Unknown template"):
            resolve_template(self._make_team(), "nonexistent_template")

    def test_feature_adoption_without_target_event_raises(self) -> None:
        with self.assertRaises(ValueError, msg="requires a target_event override"):
            resolve_template(self._make_team(), "feature_adoption")

    def test_repeat_key_behavior_without_target_event_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_template(self._make_team(), "repeat_key_behavior")

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", ["$screen"]))
    def test_likely_active_soon_resolves(self, mock_resolve: MagicMock) -> None:
        team = self._make_team()
        result = resolve_template(team, "likely_active_soon")
        self.assertIsInstance(result, ResolvedTemplate)
        self.assertEqual(result.target_event, "$pageview")
        self.assertEqual(result.resolved_activity_event, "$pageview")
        self.assertEqual(result.horizon_days, 7)
        self.assertEqual(result.output_person_property, "predicted_p_active_soon")

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_activity_event_override_respected(self, mock_resolve: MagicMock) -> None:
        result = resolve_template(self._make_team(), "likely_active_soon", target_event_override="$screen")
        self.assertEqual(result.target_event, "$screen")
        # resolved_activity_event still shows what the schema resolver found
        self.assertEqual(result.resolved_activity_event, "$pageview")

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_horizon_override_respected(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "likely_active_soon", horizon_days_override=14)
        self.assertEqual(result.horizon_days, 14)

    def test_feature_adoption_with_target_event(self) -> None:
        result = resolve_template(self._make_team(), "feature_adoption", target_event_override="feature_clicked")
        self.assertEqual(result.target_event, "feature_clicked")
        self.assertEqual(result.horizon_days, 14)
        self.assertIn("predicted_p_adopt_feature_clicked", result.output_person_property)
        self.assertEqual(result.training_population["event"], "feature_clicked")
        self.assertIsNone(result.resolved_activity_event)

    def test_repeat_key_behavior_with_target_event(self) -> None:
        result = resolve_template(self._make_team(), "repeat_key_behavior", target_event_override="$pageview")
        self.assertEqual(result.target_event, "$pageview")
        self.assertEqual(result.training_population["event"], "$pageview")
        self.assertIn("pageview", result.output_person_property)

    def test_feature_adoption_suggested_name_includes_event(self) -> None:
        result = resolve_template(self._make_team(), "feature_adoption", target_event_override="my_feature")
        self.assertIn("my feature", result.suggested_name)

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", ["$screen"]))
    def test_activity_alternatives_returned(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "at_risk_of_inactivity")
        self.assertIn("$screen", result.activity_event_alternatives)

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_return_after_first_use_population_is_first_seen(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "return_after_first_use")
        self.assertEqual(result.training_population["kind"], "person_first_seen_within_days")
        self.assertEqual(result.training_population["days"], 14)


class TestTemplateAPIEndpoints(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._flag_patcher = patch(
            "products.autoresearch.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

    def test_list_templates_returns_five(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/autoresearch/templates/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)

    def test_list_templates_has_required_keys(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/autoresearch/templates/")
        first = response.json()[0]
        for field in (
            "key",
            "display_name",
            "description",
            "default_horizon_days",
            "requires_user_event",
            "requires_activity_resolution",
        ):
            self.assertIn(field, first)

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", ["$screen"]))
    def test_resolve_template_likely_active_soon(self, _: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/autoresearch/resolve-template/",
            {"template_key": "likely_active_soon"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["target_event"], "$pageview")
        self.assertEqual(data["horizon_days"], 7)
        self.assertIn("training_population", data)
        self.assertIn("inference_population", data)
        self.assertIn("output_person_property", data)
        self.assertIn("suggested_name", data)

    def test_resolve_template_feature_adoption_requires_target_event(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/autoresearch/resolve-template/",
            {"template_key": "feature_adoption"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_resolve_template_feature_adoption_with_event(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/autoresearch/resolve-template/",
            {"template_key": "feature_adoption", "target_event": "feature_clicked"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["target_event"], "feature_clicked")

    def test_resolve_template_unknown_key_returns_400(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/autoresearch/resolve-template/",
            {"template_key": "not_a_real_template"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("products.autoresearch.backend.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_resolve_template_horizon_override(self, _: MagicMock) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/autoresearch/resolve-template/",
            {"template_key": "likely_active_soon", "horizon_days": 30},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["horizon_days"], 30)
