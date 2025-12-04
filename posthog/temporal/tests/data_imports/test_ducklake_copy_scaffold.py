import uuid

import pytest

import temporalio.converter
from parameterized import parameterized

from posthog.temporal.data_imports.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsModelInput,
    ducklake_copy_data_imports_gate_activity,
)
from posthog.temporal.utils import DuckLakeCopyWorkflowGateInputs


def test_data_imports_ducklake_copy_inputs_round_trip_serialization():
    model_input = DuckLakeCopyDataImportsModelInput(
        schema_id=uuid.uuid4(),
        schema_name="customers",
        source_type="postgres",
        normalized_name="customers",
        table_uri="s3://bucket/team_1/table",
        job_id="job-123",
        team_id=1,
    )
    inputs = DataImportsDuckLakeCopyInputs(team_id=1, job_id="job-123", models=[model_input])

    data_converter = temporalio.converter.default()
    encoded = data_converter.encode(inputs)
    decoded = data_converter.decode(encoded, DataImportsDuckLakeCopyInputs)

    assert decoded.team_id == inputs.team_id
    assert decoded.job_id == inputs.job_id
    assert decoded.models[0].normalized_name == model_input.normalized_name
    assert str(decoded.models[0].schema_id) == str(model_input.schema_id)


@pytest.mark.asyncio
@pytest.mark.django_db
@parameterized.expand([(True,), (False,)])
async def test_ducklake_copy_data_imports_gate_respects_feature_flag(monkeypatch, ateam, flag_enabled):
    captured = {}

    def fake_feature_enabled(key, distinct_id, *, groups=None, only_evaluate_locally=False):
        captured["key"] = key
        captured["distinct_id"] = distinct_id
        captured["groups"] = groups
        captured["only_evaluate_locally"] = only_evaluate_locally
        return flag_enabled

    monkeypatch.setattr(
        "posthog.temporal.data_imports.ducklake_copy_data_imports_workflow.posthoganalytics.feature_enabled",
        fake_feature_enabled,
    )

    result = await ducklake_copy_data_imports_gate_activity(DuckLakeCopyWorkflowGateInputs(team_id=ateam.id))

    assert result is flag_enabled
    assert captured["key"] == "ducklake-copy-data-imports"
    assert captured["distinct_id"] == str(ateam.uuid)
    assert captured["groups"] == {"organization": str(ateam.organization_id)}
    assert captured["only_evaluate_locally"] is True
