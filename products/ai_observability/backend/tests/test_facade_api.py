import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client.connection import Workload
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.tasks import exporter

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.trace_export import TraceExportRequest
from products.ai_observability.backend.logic.traces.trace_queries import LoadedTrace
from products.ai_observability.backend.models.evaluations import Evaluation
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.exports.backend.facade.api import ExportedAsset, InvalidExportContext, read_export_asset_content

from .logic.traces.rows import make_evaluation_result_event, make_row
from .logic.traces.test_trace_queries import TraceEventsMixin
from .property_access import hide_event_property

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def test_root_node_is_the_trace_and_nodes_keep_event_uuids() -> None:
    rows = (
        make_row(uuid="span-uuid", span_id="span", timestamp=T0),
        make_row(uuid="gen-uuid", event="$ai_generation", parent_id="span", timestamp=T0),
    )
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=rows, person=None)):
        trace = api.get_trace(team=None, user=None, trace_id="trace-1", timestamp_hint=None)  # type: ignore[arg-type]

    root = trace.tree[0]
    assert (root.id, root.kind, root.name) == ("trace-1", "trace", "Trace")
    assert [(node.id, [child.id for child in node.children]) for node in root.children] == [("span-uuid", ["gen-uuid"])]
    assert [row.id for row in trace.timeline] == ["span-uuid", "gen-uuid"]


def test_missing_trace_raises_not_found() -> None:
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=(), person=None)):
        with pytest.raises(api.TraceNotFoundError):
            api.get_trace(team=None, user=None, trace_id="missing", timestamp_hint=None)  # type: ignore[arg-type]


class TestGetTraceEvaluationResults(ClickhouseTestMixin, BaseTest):
    def _detector(self, team: Team | None = None, *, deleted: bool = False, stored_config: object = None) -> str:
        evaluation = Evaluation.objects.create(
            team=team or self.team,
            name="Mentions a competitor",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Does the answer mention a competitor?"},
            output_type="boolean",
            output_config={"true_is_failure": True},
            deleted=deleted,
        )
        if stored_config is not None:
            Evaluation.objects.filter(id=evaluation.id).update(output_config=stored_config)
        return str(evaluation.id)

    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization, name="other")

    def _detector_hidden_from_the_viewer(self) -> str:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="evaluation", access_level="none", organization_member=self.organization_membership
        )
        return self._detector()

    @parameterized.expand(
        [
            ("an active detector", lambda test: test._detector(), "fail"),
            ("a deleted detector", lambda test: test._detector(deleted=True), "fail"),
            ("another team's detector", lambda test: test._detector(test._other_team()), "pass"),
            ("a detector the viewer cannot read", lambda test: test._detector_hidden_from_the_viewer(), "pass"),
            ("an id that is not a UUID", lambda test: "not-a-uuid", "pass"),
            (
                "a detector whose stored config is not an object",
                lambda test: test._detector(stored_config=["true_is_failure"]),
                "pass",
            ),
        ]
    )
    def test_applies_the_results_stored_output_config(
        self, _name: str, evaluation_id_for: Callable[["TestGetTraceEvaluationResults"], str], outcome: str
    ) -> None:
        bulk_create_events(
            [
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000001",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_evaluation_id": evaluation_id_for(self)},
                )
            ]
        )

        [result] = api.get_trace_evaluation_results(self.team, self.user, "trace-1").results

        assert result.outcome == outcome

    def test_reads_a_registered_boolean_property_like_its_ingested_value(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team,
            name="$ai_evaluation_applicable",
            property_type="Boolean",
            type=PropertyDefinition.Type.EVENT,
        )
        bulk_create_events(
            [
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000001",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_evaluation_applicable": False},
                )
            ]
        )

        [result] = api.get_trace_evaluation_results(self.team, None, "trace-1").results

        assert (result.outcome, result.label) == ("inconclusive", "N/A")

    def test_lists_results_by_their_event_time_newest_first(self) -> None:
        live = "00000000-0000-0000-0000-000000000001"
        backfill = "00000000-0000-0000-0000-000000000002"
        bulk_create_events(
            [
                make_evaluation_result_event(uuid=live, team=self.team, timestamp=T0 + timedelta(minutes=5)),
                make_evaluation_result_event(
                    uuid=backfill,
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={
                        "$ai_evaluation_start_time": (T0 + timedelta(days=20)).isoformat(),
                        "$ai_evaluation_backfill_id": "backfill-1",
                    },
                ),
            ]
        )

        results = api.get_trace_evaluation_results(self.team, None, "trace-1").results

        assert [(result.id, result.is_backfill) for result in results] == [(live, False), (backfill, True)]


SPAN = "00000000-0000-0000-0000-000000000011"
GENERATION = "00000000-0000-0000-0000-000000000012"
LATER = "00000000-0000-0000-0000-000000000013"
ROOT_EVENT = "00000000-0000-0000-0000-000000000014"
QUESTION = [{"role": "user", "content": "Which plan fits a team of five?"}]
ANSWER = [{"role": "assistant", "content": "The team plan."}]


class TestTraceExportFile(TraceEventsMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        bulk_create_ai_events(
            [
                self._event(ROOT_EVENT, event="$ai_trace", properties={"$ai_input_state": {"question": "Why?"}}),
                self._event(
                    SPAN,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_parent_id": "trace-1", "$ai_span_id": "span-1"},
                ),
                self._event(
                    GENERATION,
                    event="$ai_generation",
                    timestamp=T0 + timedelta(seconds=2),
                    properties={
                        "$ai_parent_id": "span-1",
                        "$ai_input": QUESTION,
                        "$ai_output_choices": ANSWER,
                        "$ai_provider": "openai",
                    },
                ),
                self._event(LATER, timestamp=T0 + timedelta(seconds=3), properties={"$ai_parent_id": "trace-1"}),
            ]
        )

    def _export(self, trace_id: str = "trace-1", created_by: User | None = None) -> ExportedAsset:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format="application/json",
            export_context=TraceExportRequest(trace_id=trace_id, timestamp_hint=T0).to_context(),
            created_by=created_by or self.user,
        )
        with suppress(InvalidExportContext):
            exporter.export_asset_direct(asset)
        asset.refresh_from_db()
        return asset

    def _file(self, asset: ExportedAsset) -> contracts.TraceExportFile:
        content = read_export_asset_content(team_id=self.team.pk, asset_id=asset.id)
        assert content is not None, asset.exception
        return contracts.TraceExportFile.model_validate_json(content)

    @parameterized.expand([("one batch", 20), ("a batch per node", 1)])
    def test_writes_the_trace_and_every_node_with_its_io(self, _name: str, batch_size: int) -> None:
        with (
            patch.object(api, "TRACE_EXPORT_NODE_BATCH_SIZE", batch_size),
            patch.object(trace_queries, "query_ai_events", wraps=trace_queries.query_ai_events) as reads,
        ):
            asset = self._export()

        file = self._file(asset)
        assert asset.exception is None
        assert {call.kwargs["workload"] for call in reads.call_args_list} == {Workload.OFFLINE}
        assert file.trace.id == "trace-1"
        assert [node.id for node in file.nodes] == ["trace-1", SPAN, GENERATION, LATER]
        root, generation = file.nodes[0].event, file.nodes[2].event
        assert root is not None and root.properties["$ai_input_state"] == {"question": "Why?"}
        assert generation is not None and generation.properties["$ai_input"] == QUESTION

    def test_leaves_out_properties_the_creator_may_not_read(self) -> None:
        hide_event_property(self.team, self.user, "$ai_input")

        generation = self._file(self._export()).nodes[2].event

        assert generation is not None
        assert "$ai_input" not in generation.properties
        assert generation.properties["$ai_provider"] == "openai"

    def test_fails_when_the_creator_lost_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "trace-exporter@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )

        asset = self._export(created_by=member)

        assert (asset.exception, asset.has_content) == ("You no longer have access to this trace.", False)

    @parameterized.expand(
        [
            ("a missing trace", "trace-2", None, "This trace is no longer available."),
            ("a file over the cap", "trace-1", 10, "This trace is larger than 250 MB, so it can't be exported."),
        ]
    )
    def test_fails_as_a_user_error_and_leaves_no_file(
        self, _name: str, trace_id: str, max_bytes: int | None, message: str
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(api, "MAX_TRACE_EXPORT_BYTES", max_bytes or api.MAX_TRACE_EXPORT_BYTES),
            patch.object(tempfile, "tempdir", temporary_directory),
        ):
            asset = self._export(trace_id)
            leftover_files = list(Path(temporary_directory).iterdir())

        assert (asset.exception, asset.failure_type) == (message, "user")
        assert leftover_files == []


class TestGetTraceExport(BaseTest):
    def _asset(self, *, trace_id: str = "trace-1", created_by: User | None = None, kind: str = "llm_trace") -> int:
        context = {**TraceExportRequest(trace_id=trace_id, timestamp_hint=None).to_context(), "kind": kind}
        return ExportedAsset.objects.create(
            team=self.team, export_format="application/json", export_context=context, created_by=created_by or self.user
        ).id

    def test_reads_my_export_of_this_trace(self) -> None:
        export = api.get_trace_export(self.team, self.user, "trace-1", self._asset())

        assert (export.status, export.exception) == ("pending", None)

    @parameterized.expand(
        [
            ("another user's export", lambda test: test._asset(created_by=test._teammate()), "trace-1"),
            ("an export of another trace", lambda test: test._asset(), "trace-2"),
            ("an export of another kind", lambda test: test._asset(kind="dataset"), "trace-1"),
        ]
    )
    def test_hides(self, _name: str, asset_for: Callable[["TestGetTraceExport"], int], trace_id: str) -> None:
        with pytest.raises(api.TraceExportNotFoundError):
            api.get_trace_export(self.team, self.user, trace_id, asset_for(self))

    def _teammate(self) -> User:
        return User.objects.create_and_join(self.organization, "teammate@example.com", "testtest")
