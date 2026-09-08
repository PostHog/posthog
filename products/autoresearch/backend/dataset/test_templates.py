from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.dataset.labeling import _build_population_kind_conditions
from products.autoresearch.backend.dataset.templates import (
    TEMPLATES,
    ResolvedTemplate,
    resolve_activity_event,
    resolve_template,
)


class TestTemplateDefinitions(SimpleTestCase):
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
        self.assertIn(f"{t.default_horizon_days} days", t.description)
        self.assertNotIn("{", t.description)
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


class TestTemplateSpecsCompile(SimpleTestCase):
    # Drift guard: every template's population spec must have a compiler branch in
    # labeling.py, in both row mode (inference/eligible count) and anchor mode (training).

    @parameterized.expand(list(TEMPLATES.keys()))
    def test_population_specs_compile_in_both_modes(self, key: str) -> None:
        t = TEMPLATES[key]
        for population in (t.training_population_spec, t.inference_population_spec):
            row = _build_population_kind_conditions(population, target_cond="event = {target}")
            anchor = _build_population_kind_conditions(population, anchor_mode=True, target_cond="event = {target}")
            self.assertTrue(row.where_parts)
            self.assertTrue(anchor.anchor_having_parts)


class TestResolveActivityEvent(SimpleTestCase):
    def test_ranks_candidates_over_identified_users_only(self) -> None:
        # Training and scoring only see identified users, so an event that only anonymous
        # traffic emits must not be chosen as the activity signal.
        team = MagicMock()
        team.pk = 1
        user = MagicMock()
        with patch(
            "products.autoresearch.backend.dataset.templates.run_hogql_rows",
            return_value=[["$pageview", 10]],
        ) as mock_run:
            resolved, _alternatives = resolve_activity_event(team, user=user)
        self.assertEqual(resolved, "$pageview")
        query = mock_run.call_args.kwargs["query"].query
        self.assertIn("person.is_identified", query)
        self.assertIn("uniq(person_id)", query)
        self.assertIs(mock_run.call_args.kwargs["user"], user)

    @parameterized.expand(
        [
            # A preferred event wins over a busier custom event; bookkeeping never wins.
            ([["$identify", 50], ["clicked", 20], ["$pageview", 10]], "$pageview", ["clicked"]),
            # Equal coverage breaks ties by name, so a cache refresh cannot flip the target.
            ([["$identify", 50], ["heartbeat", 20], ["clicked", 20]], "clicked", ["heartbeat"]),
            ([["x" * 300, 40], ["clicked", 20]], "clicked", []),
            ([["$identify", 50]], None, []),
            ([], None, []),
        ]
    )
    def test_ranking(self, rows: list[list[object]], expected: str | None, expected_alternatives: list[str]) -> None:
        with patch("products.autoresearch.backend.dataset.templates.run_hogql_rows", return_value=rows):
            resolved, alternatives = resolve_activity_event(MagicMock())
        self.assertEqual(resolved, expected)
        self.assertEqual(alternatives, expected_alternatives)


class TestResolveTemplate(SimpleTestCase):
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

    @parameterized.expand([(0,), (-3,)])
    def test_non_positive_horizon_raises(self, horizon: int) -> None:
        with self.assertRaises(ValueError, msg="horizon_days must be at least 1"):
            resolve_template(self._make_team(), "feature_adoption", "signed_up", horizon_days_override=horizon)

    @patch("products.autoresearch.backend.dataset.templates.resolve_activity_event", return_value=(None, []))
    def test_unresolved_activity_event_raises_without_override(self, _: MagicMock) -> None:
        with self.assertRaises(ValueError, msg="could not resolve an activity event"):
            resolve_template(self._make_team(), "likely_active_soon")
        result = resolve_template(self._make_team(), "likely_active_soon", target_event_override="$screen")
        self.assertEqual(result.target_event, "$screen")

    @patch(
        "products.autoresearch.backend.dataset.templates.resolve_activity_event",
        return_value=("$pageview", ["$screen"]),
    )
    def test_likely_active_soon_resolves(self, mock_resolve: MagicMock) -> None:
        team = self._make_team()
        user = MagicMock()
        result = resolve_template(team, "likely_active_soon", user=user)
        mock_resolve.assert_called_once_with(team, user=user)
        self.assertIsInstance(result, ResolvedTemplate)
        self.assertEqual(result.target_event, "$pageview")
        self.assertEqual(result.resolved_activity_event, "$pageview")
        self.assertEqual(result.horizon_days, 7)
        self.assertEqual(result.output_person_property, "predicted_p_active_soon_pageview_7d")
        self.assertEqual(
            result.training_population, {"kind": "performed_event_within_days", "days": 30, "event": "$pageview"}
        )
        self.assertEqual(result.inference_population["event"], "$pageview")

    @patch("products.autoresearch.backend.dataset.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_activity_event_override_respected(self, mock_resolve: MagicMock) -> None:
        result = resolve_template(self._make_team(), "likely_active_soon", target_event_override="$screen")
        self.assertEqual(result.target_event, "$screen")
        self.assertEqual(result.training_population["event"], "$screen")
        self.assertEqual(result.output_person_property, "predicted_p_active_soon_screen_7d")
        # resolved_activity_event still shows what the schema resolver found
        self.assertEqual(result.resolved_activity_event, "$pageview")

    @patch("products.autoresearch.backend.dataset.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_horizon_override_respected(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "likely_active_soon", horizon_days_override=14)
        self.assertEqual(result.horizon_days, 14)
        self.assertIn("14 days", result.description)
        # Horizon is part of the output property so the same target over a different horizon
        # does not clobber another pipeline's score.
        self.assertEqual(result.output_person_property, "predicted_p_active_soon_pageview_14d")

    def test_feature_adoption_with_target_event(self) -> None:
        result = resolve_template(self._make_team(), "feature_adoption", target_event_override="feature_clicked")
        self.assertEqual(result.target_event, "feature_clicked")
        self.assertEqual(result.horizon_days, 14)
        self.assertEqual(result.output_person_property, "predicted_p_adopt_feature_clicked_14d")
        self.assertEqual(result.training_population, {"kind": "active_not_performed_target", "active_within_days": 30})
        self.assertIsNone(result.resolved_activity_event)

    def test_repeat_key_behavior_with_target_event(self) -> None:
        result = resolve_template(self._make_team(), "repeat_key_behavior", target_event_override="$pageview")
        self.assertEqual(result.target_event, "$pageview")
        self.assertEqual(result.training_population, {"kind": "ever_performed_target"})
        self.assertIn("pageview", result.output_person_property)

    def test_feature_adoption_suggested_name_includes_event(self) -> None:
        result = resolve_template(self._make_team(), "feature_adoption", target_event_override="my_feature")
        self.assertIn("my feature", result.suggested_name)

    def test_targets_that_normalize_alike_keep_distinct_properties(self) -> None:
        lossy = resolve_template(self._make_team(), "feature_adoption", target_event_override="Checkout Started")
        exact = resolve_template(self._make_team(), "feature_adoption", target_event_override="checkout_started")
        self.assertTrue(lossy.output_person_property.startswith("predicted_p_adopt_checkout_started_"))
        self.assertEqual(exact.output_person_property, "predicted_p_adopt_checkout_started_14d")
        self.assertNotEqual(lossy.output_person_property, exact.output_person_property)
        # An event literally named like the encoded form of another event still gets its own property.
        encoded = lossy.output_person_property.removeprefix("predicted_p_adopt_").removesuffix("_14d")
        literal = resolve_template(self._make_team(), "feature_adoption", target_event_override=encoded)
        self.assertNotEqual(literal.output_person_property, lossy.output_person_property)

    def test_overlong_target_override_raises(self) -> None:
        with self.assertRaises(ValueError, msg="target_event must be at most 255 characters"):
            resolve_template(self._make_team(), "feature_adoption", target_event_override="a" * 256)

    def test_long_target_fits_pipeline_columns(self) -> None:
        result = resolve_template(self._make_team(), "feature_adoption", target_event_override="a" * 250)
        self.assertLessEqual(len(result.output_person_property), 255)
        self.assertTrue(result.output_person_property.endswith("_14d"))
        self.assertLessEqual(len(result.suggested_name), 255)

    @patch(
        "products.autoresearch.backend.dataset.templates.resolve_activity_event",
        return_value=("$pageview", ["$screen"]),
    )
    def test_activity_alternatives_returned(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "at_risk_of_inactivity")
        self.assertIn("$screen", result.activity_event_alternatives)

    @patch("products.autoresearch.backend.dataset.templates.resolve_activity_event", return_value=("$pageview", []))
    def test_return_after_first_use_population_is_first_seen(self, _: MagicMock) -> None:
        result = resolve_template(self._make_team(), "return_after_first_use")
        self.assertEqual(result.training_population, {"kind": "person_first_seen_within_days", "days": 14})
