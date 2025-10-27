from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.read_data import ReadDataTool
from ee.hogai.tool import MaxToolError, MaxToolErrorCode
from ee.hogai.utils.types import AssistantState


class TestReadDataTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = ReadDataTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
        )

    async def test_billing_info_without_access_raises_permission_error(self):
        """Test that billing_info raises MaxToolError with permission_denied when user lacks access"""
        with patch.object(self.context_manager, "check_user_has_billing_access", return_value=False):
            with self.assertRaises(MaxToolError) as context:
                await self.tool._arun_impl(kind="billing_info")

            self.assertEqual(context.exception.code, MaxToolErrorCode.PERMISSION_DENIED)
            self.assertIn("admin", str(context.exception).lower())

    async def test_billing_info_with_access_calls_billing_tool(self):
        """Test that billing_info successfully calls ReadBillingTool when user has access"""
        mock_billing_result = "Billing information here"

        with (
            patch.object(self.context_manager, "check_user_has_billing_access", return_value=True),
            patch("ee.hogai.graph.root.tools.read_data.ReadBillingTool") as mock_billing_tool_class,
        ):
            mock_billing_tool = mock_billing_tool_class.return_value
            mock_billing_tool.execute = AsyncMock(return_value=mock_billing_result)

            result, artifact = await self.tool._arun_impl(kind="billing_info")

            self.assertEqual(result, mock_billing_result)
            self.assertIsNone(artifact)
            mock_billing_tool.execute.assert_called_once()

    async def test_datawarehouse_schema_returns_schema(self):
        """Test that datawarehouse_schema kind returns database schema"""
        with patch.object(self.tool, "_serialize_database_schema", return_value="Database schema here"):
            result, artifact = await self.tool._arun_impl(kind="datawarehouse_schema")

            self.assertEqual(result, "Database schema here")
            self.assertIsNone(artifact)
