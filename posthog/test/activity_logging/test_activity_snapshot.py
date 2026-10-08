from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest

from django.db import models

from parameterized import parameterized

from posthog.models import Integration
from posthog.models.activity_logging.activity_log import AuditableScope, Change, changes_between
from posthog.models.activity_logging.snapshot import ActivitySnapshot, diff_snapshots

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.feature_flags.backend.models.feature_flag import FeatureFlag

SECRET = "sk-test-not-a-real-secret"


def _feature_flag(test: BaseTest) -> models.Model:
    return FeatureFlag.objects.create(
        team=test.team,
        key="beta",
        created_by=test.user,
        filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
    )


def _edit_feature_flag(flag: Any) -> None:
    flag.filters["groups"][0]["rollout_percentage"] = 50
    flag.name = "Beta rollout"


def _hog_function(test: BaseTest) -> models.Model:
    return HogFunction.objects.create(
        team=test.team,
        name="Webhook",
        hog="return event",
        type="destination",
        inputs_schema=[{"key": "url", "type": "string"}, {"key": "token", "type": "string"}],
        inputs={"url": {"value": "https://example.com"}, "token": {"value": SECRET}},
    )


def _edit_hog_function(hog_function: Any) -> None:
    hog_function.inputs["token"]["value"] = "sk-test-rotated"
    hog_function.name = "Rotated webhook"


def _integration(test: BaseTest) -> models.Model:
    return Integration.objects.create(team=test.team, kind="slack", config={"team": "example", "bot_token": SECRET})


def _edit_integration(integration: Any) -> None:
    integration.config["bot_token"] = "sk-test-rotated"


class TestActivitySnapshot(BaseTest):
    @parameterized.expand(
        [
            ("FeatureFlag", _feature_flag, _edit_feature_flag, None),
            (
                "HogFunction",
                _hog_function,
                _edit_hog_function,
                Change(
                    type="HogFunction",
                    field="inputs",
                    action="changed",
                    before={"url": "masked", "token": "masked"},
                    after={"url": "masked", "token": "changed"},
                ),
            ),
            (
                "Integration",
                _integration,
                _edit_integration,
                Change(type="Integration", field="config", action="changed", before="masked", after="masked"),
            ),
        ]
    )
    def test_snapshot_diff_matches_the_model_diff_after_an_in_place_edit(
        self,
        scope: AuditableScope,
        create: Callable[[BaseTest], models.Model],
        edit: Callable[[Any], None],
        expected_masked_change: Change | None,
    ) -> None:
        instance = create(self)
        previous = type(instance).objects.get(pk=instance.pk)  # type: ignore[attr-defined]

        before = ActivitySnapshot.of(scope, instance)
        edit(instance)
        instance.save()
        after = ActivitySnapshot.of(scope, instance)

        changes = diff_snapshots(scope, before, after)
        assert changes
        assert changes == changes_between(scope, previous=previous, current=instance)
        if expected_masked_change is not None:
            assert expected_masked_change in changes

    @parameterized.expand([("HogFunction", _hog_function), ("Integration", _integration)])
    def test_masked_values_never_leave_the_snapshot(
        self, scope: AuditableScope, create: Callable[[BaseTest], models.Model]
    ) -> None:
        snapshot = ActivitySnapshot.of(scope, create(self))

        assert SECRET not in repr(snapshot)
        assert all(SECRET not in str(captured.value) for captured in snapshot.fields)

    def test_unchanged_masked_field_gives_no_change(self) -> None:
        integration = _integration(self)

        before = ActivitySnapshot.of("Integration", integration)
        integration.save()

        assert diff_snapshots("Integration", before, ActivitySnapshot.of("Integration", integration)) == []
