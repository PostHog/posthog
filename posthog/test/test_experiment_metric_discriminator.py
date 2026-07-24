from django.test.testcases import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import ExperimentMetric


class TestExperimentMetricDiscriminator(SimpleTestCase):
    @parameterized.expand(
        [
            # Each payload uses the mean-metric shape (`source`) but declares a non-mean
            # `metric_type`. A correctly-routed error must (a) start with the declared
            # tag in the loc, and (b) name a field that is REQUIRED by the target class
            # but missing here — proving Pydantic validated against the right shape,
            # not just emitted the right tag prefix.
            ("funnel_routes_to_funnel", "funnel", "series"),
            ("ratio_routes_to_ratio", "ratio", "numerator"),
            ("retention_routes_to_retention", "retention", "start_event"),
        ]
    )
    def test_invalid_payload_routes_to_class_named_by_metric_type(
        self, _name: str, metric_type: str, target_class_required_field: str
    ) -> None:
        payload = {"metric_type": metric_type, "source": {"kind": "EventsNode", "event": "x"}}

        with self.assertRaises(ValidationError) as ctx:
            ExperimentMetric.model_validate(payload)

        errors = ctx.exception.errors()
        assert errors, "expected at least one validation error"

        for err in errors:
            assert err["loc"][0] == metric_type, (
                f"error loc[0] should be the discriminator tag {metric_type!r}, "
                f"got {err['loc'][0]!r} — discriminator likely dropped"
            )

        # Positive routing check: the field the *target* class requires must appear as
        # missing. An undiscriminated union would walk variants in order, fail on
        # ExperimentMeanMetric's metric_type literal, and never reach this field.
        missing_field_locs = {err["loc"] for err in errors if err["type"] == "missing"}
        assert (metric_type, target_class_required_field) in missing_field_locs, (
            f"expected missing-field error on ({metric_type!r}, {target_class_required_field!r}) "
            f"to prove routing to the target class; got {missing_field_locs}"
        )

        assert "ExperimentMeanMetric" not in str(ctx.exception), (
            "error should target the variant named by metric_type, not ExperimentMeanMetric — "
            "discriminator likely dropped"
        )

    def test_unknown_metric_type_returns_clean_tag_error(self) -> None:
        # Anything that isn't one of the four literals produces `union_tag_invalid` with
        # the valid tag list, instead of cascading errors from every variant.
        with self.assertRaises(ValidationError) as ctx:
            ExperimentMetric.model_validate(
                {"metric_type": "banana", "source": {"kind": "EventsNode", "event": "purchase"}}
            )

        errors = ctx.exception.errors()
        assert len(errors) == 1
        assert errors[0]["type"] == "union_tag_invalid"
        expected_tags_str = errors[0]["ctx"]["expected_tags"]
        for tag in ("mean", "funnel", "ratio", "retention"):
            assert f"'{tag}'" in expected_tags_str, f"expected tag {tag!r} not found in {expected_tags_str!r}"

    def test_missing_metric_type_returns_clean_tag_error(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            ExperimentMetric.model_validate({"source": {"kind": "EventsNode", "event": "purchase"}})

        errors = ctx.exception.errors()
        assert len(errors) == 1
        assert errors[0]["type"] == "union_tag_not_found"

    @parameterized.expand(
        [
            ("mean", {"metric_type": "mean", "source": {"kind": "EventsNode", "event": "purchase"}}),
            ("funnel", {"metric_type": "funnel", "series": [{"kind": "EventsNode", "event": "view"}]}),
            (
                "ratio",
                {
                    "metric_type": "ratio",
                    "numerator": {"kind": "EventsNode", "event": "revenue"},
                    "denominator": {"kind": "EventsNode", "event": "pageview"},
                },
            ),
            (
                "retention",
                {
                    "metric_type": "retention",
                    "start_event": {"kind": "EventsNode", "event": "signup"},
                    "completion_event": {"kind": "EventsNode", "event": "activated"},
                    "retention_window_start": 0,
                    "retention_window_end": 7,
                    "retention_window_unit": "day",
                    "start_handling": "first_seen",
                },
            ),
        ]
    )
    def test_valid_payload_per_metric_type_still_validates(self, _name: str, payload: dict) -> None:
        ExperimentMetric.model_validate(payload)


class TestExperimentMetricSourceDiscriminator(SimpleTestCase):
    # The inner union `EventsNode | ActionsNode | ExperimentDataWarehouseNode` used by
    # mean.source, funnel.series, ratio.numerator/denominator, and
    # retention.start_event/completion_event was undiscriminated — Pydantic would walk
    # every variant and report errors for each, producing payloads like
    #   ('funnel', 'series', 0, 'EventsNode', 'id'), 'extra_forbidden'
    #   ('funnel', 'series', 0, 'ActionsNode', 'id'), 'int_type'
    #   ('funnel', 'series', 0, 'ActionsNode', 'kind'), 'literal_error'
    # all from a single malformed EventsNode submission, leaving LLM callers unable to
    # tell which variant they meant to populate. These tests assert that tagging the
    # union on `kind` narrows errors to exactly one variant.

    _ALL_KINDS = ("EventsNode", "ActionsNode", "ExperimentDataWarehouseNode")

    @parameterized.expand(
        [
            # (case_name, payload, declared_kind_in_payload, location_path_to_source)
            (
                "mean_source_eventsnode",
                {"metric_type": "mean", "source": {"kind": "EventsNode", "id": 5}},
                "EventsNode",
                ("mean", "source"),
            ),
            (
                "mean_source_actionsnode",
                {"metric_type": "mean", "source": {"kind": "ActionsNode", "event": "purchase"}},
                "ActionsNode",
                ("mean", "source"),
            ),
            (
                "funnel_series_eventsnode",
                {"metric_type": "funnel", "series": [{"kind": "EventsNode", "id": 5}]},
                "EventsNode",
                ("funnel", "series", 0),
            ),
            (
                "funnel_series_actionsnode",
                {"metric_type": "funnel", "series": [{"kind": "ActionsNode", "event": "view"}]},
                "ActionsNode",
                ("funnel", "series", 0),
            ),
            (
                "ratio_numerator_eventsnode",
                {
                    "metric_type": "ratio",
                    "numerator": {"kind": "EventsNode", "id": 5},
                    "denominator": {"kind": "EventsNode", "event": "pageview"},
                },
                "EventsNode",
                ("ratio", "numerator"),
            ),
            (
                "retention_start_event_actionsnode",
                {
                    "metric_type": "retention",
                    "start_event": {"kind": "ActionsNode", "event": "signup"},
                    "completion_event": {"kind": "EventsNode", "event": "activated"},
                    "retention_window_start": 0,
                    "retention_window_end": 7,
                    "retention_window_unit": "day",
                    "start_handling": "first_seen",
                },
                "ActionsNode",
                ("retention", "start_event"),
            ),
        ]
    )
    def test_invalid_source_routes_to_declared_kind_only(
        self,
        _name: str,
        payload: dict,
        declared_kind: str,
        location_path: tuple,
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            ExperimentMetric.model_validate(payload)

        errors = ctx.exception.errors()
        assert errors, "expected at least one validation error"

        # Errors for THIS source field must reach the declared kind tag and no other
        # variant must appear at this loc prefix.
        source_errors = [err for err in errors if err["loc"][: len(location_path)] == location_path]
        assert source_errors, (
            f"expected at least one error under loc prefix {location_path!r}; got locs {[err['loc'] for err in errors]}"
        )

        kinds_in_source_loc = {
            err["loc"][len(location_path)]
            for err in source_errors
            if len(err["loc"]) > len(location_path) and err["loc"][len(location_path)] in self._ALL_KINDS
        }
        assert kinds_in_source_loc == {declared_kind}, (
            f"errors under {location_path!r} should reach exactly one variant tag "
            f"{declared_kind!r}; got {kinds_in_source_loc!r} — inner-union discriminator likely dropped"
        )

    def test_unknown_kind_in_source_returns_clean_tag_error(self) -> None:
        # Submitting kind='banana' must yield a single union_tag_invalid error naming
        # the valid variants, not a multi-variant pile.
        with self.assertRaises(ValidationError) as ctx:
            ExperimentMetric.model_validate({"metric_type": "mean", "source": {"kind": "banana", "event": "purchase"}})

        errors = ctx.exception.errors()
        source_errors = [err for err in errors if err["loc"][:2] == ("mean", "source")]
        assert len(source_errors) == 1, (
            f"expected exactly one error for malformed source; got {len(source_errors)}: {source_errors}"
        )
        assert source_errors[0]["type"] == "union_tag_invalid"
        expected_tags_str = source_errors[0]["ctx"]["expected_tags"]
        for tag in self._ALL_KINDS:
            assert f"'{tag}'" in expected_tags_str, f"expected tag {tag!r} in {expected_tags_str!r}"

    @parameterized.expand(
        [
            ("eventsnode", {"kind": "EventsNode", "event": "purchase"}),
            ("actionsnode", {"kind": "ActionsNode", "id": 5}),
        ]
    )
    def test_valid_source_still_validates(self, _name: str, source: dict) -> None:
        ExperimentMetric.model_validate({"metric_type": "mean", "source": source})
