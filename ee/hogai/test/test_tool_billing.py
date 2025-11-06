from posthog.test.base import NonAtomicBaseTest

from products.data_warehouse.backend.max_tools import HogQLGeneratorTool

from ee.hogai.utils.types import AssistantState


class TestMaxToolBilling(NonAtomicBaseTest):
    def test_tool_billable_field_accessible(self):
        """Test that MaxTool billable field is accessible."""
        tool = HogQLGeneratorTool(
            team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
        )
        # HogQLGeneratorTool should have billable=True
        self.assertEqual(tool.billable, True)

    def test_hogql_generator_tool_is_billable(self):
        """Test that HogQLGeneratorTool is marked as billable."""
        tool = HogQLGeneratorTool(
            team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
        )
        # Verify the tool has billable=True as defined in the class
        self.assertTrue(tool.billable)
        self.assertEqual(tool.billable, True)
