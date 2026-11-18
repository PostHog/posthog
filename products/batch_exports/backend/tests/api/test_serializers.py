import uuid
import datetime as dt
import dataclasses
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.batch_exports.backend.facade import (
    api as batch_exports_api,
    contracts,
)
from products.batch_exports.backend.presentation.views.batch_export.destinations import BatchExportDestinationSerializer
from products.batch_exports.backend.presentation.views.batch_export.exports import BatchExportSerializer

_CONFIGURATION = contracts.BatchExportConfiguration(
    id=uuid.uuid4(),
    team_id=1,
    name="An export",
    model="events",
    destination=contracts.BatchExportDestinationConfiguration(type="NoOp", config={}, integration=None),
    interval="hour",
    paused=False,
    created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    last_updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    last_paused_at=None,
    start_at=None,
    end_at=None,
    latest_runs=(),
    hogql_query=None,
    hogql_modifiers=None,
    primary_key=None,
    version_key=None,
    incremental_mode="APPEND",
    schema=None,
    filters=None,
    timezone="UTC",
    offset_day=None,
    offset_hour=None,
)


def make_configuration(**overrides: Any) -> contracts.BatchExportConfiguration:
    return dataclasses.replace(_CONFIGURATION, **overrides)


class TestBatchExportModelValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("persons", "filters", []),
            ("sessions", "filters", []),
            ("hogql", "filters", []),
            ("persons", "hogql_query", "SELECT uuid FROM events"),
            ("sessions", "hogql_query", "SELECT uuid FROM events"),
            ("events", "hogql_modifiers", {}),
        ]
    )
    def test_rejects_unsupported_fields(self, model: str, field: str, value: object) -> None:
        serializer = BatchExportSerializer(make_configuration(model=model), data={field: value}, partial=True)

        assert not serializer.is_valid()
        assert field in serializer.errors

    @parameterized.expand([("events",), ("persons",), ("sessions",)])
    def test_patch_without_model_specific_fields(self, model: str) -> None:
        serializer = BatchExportSerializer(make_configuration(model=model), data={"name": "Renamed"}, partial=True)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {"name": "Renamed"}


class TestBatchExportIncrementalMode(BaseTest):
    @parameterized.expand([("events",), ("hogql",)])
    def test_create_and_patch_incremental_mode(self, model: str) -> None:
        context = {
            "team_id": self.team.pk,
            "get_team": lambda: self.team,
            "request": SimpleNamespace(user=self.user, method="POST"),
        }
        data = {
            "name": "Incremental export",
            "model": model,
            "interval": "hour",
            "destination": {"type": "NoOp", "config": {}},
            "incremental_mode": "MERGE",
        }
        if model == "hogql":
            data.update(hogql_query="SELECT uuid FROM events", primary_key=["uuid"])

        with (
            team_scope(self.team.pk),
            patch("products.batch_exports.backend.service.sync_batch_export"),
            patch(
                "products.batch_exports.backend.presentation.views.utils.posthoganalytics.feature_enabled",
                return_value=True,
            ),
        ):
            serializer = BatchExportSerializer(data=data, context=context)
            assert serializer.is_valid(), serializer.errors
            batch_export = serializer.save()
            assert batch_exports_api.get_batch_export(self.team.pk, batch_export.id).incremental_mode == "MERGE"
            assert BatchExportSerializer(batch_export).data["incremental_mode"] == "MERGE"

            serializer = BatchExportSerializer(
                batch_export, data={"name": "Renamed export"}, partial=True, context=context
            )
            assert serializer.is_valid(), serializer.errors
            batch_export = serializer.save()
            assert batch_exports_api.get_batch_export(self.team.pk, batch_export.id).incremental_mode == "MERGE"

            serializer = BatchExportSerializer(
                batch_export, data={"incremental_mode": "APPEND"}, partial=True, context=context
            )
            assert serializer.is_valid(), serializer.errors
            batch_export = serializer.save()
            assert batch_exports_api.get_batch_export(self.team.pk, batch_export.id).incremental_mode == "APPEND"
            assert BatchExportSerializer(batch_export).data["incremental_mode"] == "APPEND"

    @parameterized.expand([("MERGE", False), ("APPEND", True)])
    def test_patch_validates_keys_against_saved_export_mode(self, mode: str, valid: bool) -> None:
        batch_export = make_configuration(
            team_id=self.team.pk,
            model="hogql",
            incremental_mode=mode,
            hogql_query="SELECT uuid FROM events",
            primary_key=("uuid",),
        )
        serializer = BatchExportSerializer(
            batch_export,
            data={"primary_key": None},
            partial=True,
            context={
                "team_id": self.team.pk,
                "get_team": lambda: self.team,
                "request": SimpleNamespace(user=self.user),
            },
        )

        assert serializer.is_valid() is valid, serializer.errors
        if not valid:
            assert "primary_key" in serializer.errors


class TestBatchExportDestinationSerializerTeamScoping(BaseTest):
    def _make_integration(self, team: Team) -> Integration:
        return Integration.objects.create(team=team, kind="databricks", integration_id="server")

    @parameterized.expand([("integration",), ("integration_id",)])
    def test_field_rejects_cross_team_integration(self, field_name):
        foreign_org = Organization.objects.create(name="Foreign")
        foreign_team = Team.objects.create(organization=foreign_org, name="Foreign")
        foreign_integration = self._make_integration(foreign_team)

        serializer = BatchExportDestinationSerializer(
            data={
                "type": "Databricks",
                "config": {
                    "http_path": "/sql/1.0/warehouses/abc",
                    "catalog": "main",
                    "schema": "default",
                    "table_name": "events",
                },
                field_name: foreign_integration.pk,
            },
            context={"team_id": self.team.pk},
        )
        assert not serializer.is_valid()
        assert field_name in serializer.errors

    @parameterized.expand([("integration",), ("integration_id",)])
    def test_field_accepts_same_team_integration(self, field_name):
        own_integration = self._make_integration(self.team)

        serializer = BatchExportDestinationSerializer(context={"team_id": self.team.pk})
        assert serializer.fields[field_name].run_validation(own_integration.pk) == own_integration
