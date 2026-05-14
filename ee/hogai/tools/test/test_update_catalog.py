from datetime import date
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.update_catalog import (
    RecordJoinArgs,
    UpdateCatalogTool,
    UpdateColumnNoteArgs,
    UpdateTableNoteArgs,
    _attribution_handle,
    _build_attribution,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestAttributionFormat(NonAtomicBaseTest):
    """The attribution string is embedded verbatim in catalog descriptions — keep it stable."""

    def test_handle_uses_email_local_part(self):
        self.user.email = "aspicer@gmail.com"
        assert _attribution_handle(self.user) == "aspicer"

    def test_handle_falls_back_to_uuid_prefix_when_no_email(self):
        self.user.email = ""
        handle = _attribution_handle(self.user)
        assert handle == str(self.user.uuid)[:8]

    def test_attribution_format(self):
        self.user.email = "aspicer@gmail.com"
        attribution = _build_attribution(self.user, when=date(2026, 5, 14))
        assert attribution == "[@aspicer 2026-05-14]"


class TestUpdateCatalogTool(ClickhouseTestMixin, NonAtomicBaseTest):
    """The MaxTool wires together attribution, kind resolution, and the facade appends."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.user.email = "alice@example.com"
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = UpdateCatalogTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_update_table_records_note_with_attribution(self):
        with patch("ee.hogai.tools.update_catalog.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 14)
            result, artifact = await self.tool._arun_impl(
                args=UpdateTableNoteArgs(
                    action="update_table",
                    table_name="events",
                    note="excludes staging traffic",
                )
            )
        assert artifact["action"] == "update_table"
        assert artifact["table"] == "events"
        assert "events" in result
        assert "[@alice 2026-05-14] excludes staging traffic" in result

        node = await sync_to_async(CatalogNode.objects.get)(
            team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events"
        )
        assert node.synthetic_description == "[@alice 2026-05-14] excludes staging traffic"

    async def test_update_column_records_note(self):
        with patch("ee.hogai.tools.update_catalog.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 14)
            result, artifact = await self.tool._arun_impl(
                args=UpdateColumnNoteArgs(
                    action="update_column",
                    table_name="events",
                    column_name="timestamp",
                    note="UTC, not user local time",
                )
            )
        assert artifact["action"] == "update_column"
        assert artifact["target"] == "events.timestamp"
        assert "[@alice 2026-05-14] UTC, not user local time" in result

        column = await sync_to_async(CatalogColumn.objects.get)(team=self.team, node__name="events", name="timestamp")
        assert column.synthetic_description == "[@alice 2026-05-14] UTC, not user local time"

    async def test_record_join_creates_declared_join(self):
        with patch("ee.hogai.tools.update_catalog.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 14)
            result, artifact = await self.tool._arun_impl(
                args=RecordJoinArgs(
                    action="record_join",
                    source_table="events",
                    target_table="persons",
                    source_column="distinct_id",
                    note="primary person link",
                )
            )
        assert artifact["action"] == "record_join"
        assert artifact["source"] == "events.distinct_id"
        assert artifact["target"] == "persons"
        assert "↔" in result

        edge = await sync_to_async(CatalogRelationship.objects.get)(id=artifact["relationship_id"])
        assert edge.kind == CatalogRelationship.Kind.DECLARED_JOIN
        assert edge.status == CatalogRelationship.Status.ACCEPTED
        assert edge.confidence == 1.0
        assert "[@alice 2026-05-14] primary person link" in edge.reasoning

    async def test_unknown_table_raises_retryable(self):
        with self.assertRaises(MaxToolRetryableError):
            await self.tool._arun_impl(
                args=UpdateTableNoteArgs(
                    action="update_table",
                    table_name="definitely_not_a_real_table_zzz",
                    note="anything",
                )
            )
