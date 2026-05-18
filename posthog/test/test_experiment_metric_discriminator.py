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
