from __future__ import annotations

from pathlib import Path

import pytest
from unittest import mock

from django.core.management.base import CommandError

from posthog.management.commands.upload_surfacing_model import Command
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.conftest import train_synthetic_booster


@pytest.fixture
def valid_booster_path(tmp_path: Path) -> Path:
    booster = train_synthetic_booster(tuple(FEATURE_RANGES.keys()))
    path = tmp_path / "model.ubj"
    booster.save_model(str(path))
    return path


def _run_upload(**options: object) -> None:
    Command().handle(**options)


class TestUploadSurfacingModelCommand:
    def test_rejects_missing_file(self) -> None:
        with pytest.raises(CommandError, match="does not exist"):
            _run_upload(path="/tmp/definitely-missing-model.ubj", bucket=None, key="k.ubj", skip_validate=False)

    def test_rejects_booster_with_schema_drift(self, tmp_path: Path) -> None:
        # Drift now means a feature the SQL universe doesn't contain (a subset
        # of real features is valid — see test_uploads_strict_subset_booster).
        drifted = train_synthetic_booster(("event_rate", "feature_the_sql_never_produces"))
        path = tmp_path / "drifted.ubj"
        drifted.save_model(str(path))

        with pytest.raises(CommandError, match="doesn't match current SQL/FEATURE_RANGES"):
            _run_upload(path=str(path), bucket=None, key="k.ubj", skip_validate=False)

    def test_uploads_valid_booster(self, valid_booster_path: Path) -> None:
        with mock.patch(
            "posthog.management.commands.upload_surfacing_model.object_storage.write_from_file"
        ) as write_mock:
            _run_upload(path=str(valid_booster_path), bucket="test-bucket", key="k.ubj", skip_validate=False)

        write_mock.assert_called_once_with(file_name="k.ubj", file_path=str(valid_booster_path), bucket="test-bucket")

    def test_uploads_strict_subset_booster(self, tmp_path: Path) -> None:
        # The production booster scores a subset of the serving query's features;
        # the upload validator must accept it.
        subset = tuple(FEATURE_RANGES.keys())[::2]
        booster = train_synthetic_booster(subset)
        path = tmp_path / "subset.ubj"
        booster.save_model(str(path))

        with mock.patch(
            "posthog.management.commands.upload_surfacing_model.object_storage.write_from_file"
        ) as write_mock:
            _run_upload(path=str(path), bucket="test-bucket", key="k.ubj", skip_validate=False)

        write_mock.assert_called_once()

    def test_skip_validate_bypasses_schema_check(self, tmp_path: Path) -> None:
        drifted = train_synthetic_booster(("event_rate", "feature_the_sql_never_produces"))
        path = tmp_path / "drifted.ubj"
        drifted.save_model(str(path))

        with mock.patch(
            "posthog.management.commands.upload_surfacing_model.object_storage.write_from_file"
        ) as write_mock:
            _run_upload(path=str(path), bucket=None, key="k.ubj", skip_validate=True)

        write_mock.assert_called_once()
