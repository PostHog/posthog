import pytest
from unittest import mock

from posthog.temporal.data_imports.workflow_activities import sync_new_schemas as module
from posthog.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(source_mock):
    """Patch DB + registry so the activity runs without a database or real source."""
    existing_source = mock.MagicMock(source_type="GoogleAds", job_inputs={"k": "v"}, deleted=False)
    objects = mock.MagicMock()
    objects.filter.return_value.exclude.return_value.exists.return_value = True
    objects.get.return_value = existing_source

    return (
        mock.patch.object(module, "close_old_connections"),
        mock.patch.object(module.ExternalDataSource, "objects", objects),
        mock.patch.object(module, "ExternalDataSourceType", return_value="GoogleAds"),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "sync_old_schemas_with_new_schemas", return_value=([], [])),
    )


def _run_activity(source_mock):
    patches = _patch_common(source_mock)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))


def test_non_retryable_get_schemas_error_is_skipped():
    """A non-retryable source error during discovery must be swallowed, not retried."""
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(
        "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})"
    )
    source_mock.get_non_retryable_errors.return_value = {"invalid_grant": None}

    # Should not raise — the error matches a non-retryable pattern and is skipped.
    _run_activity(source_mock)


def test_unknown_get_schemas_error_propagates():
    """An error that is not classified as non-retryable must still propagate (and retry)."""
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception("UNAVAILABLE: transient network blip")
    source_mock.get_non_retryable_errors.return_value = {"invalid_grant": None}

    with pytest.raises(Exception, match="transient network blip"):
        _run_activity(source_mock)
