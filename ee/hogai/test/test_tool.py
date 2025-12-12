from posthog.test.base import BaseTest

from pydantic import BaseModel

from ee.hogai.core.context import set_node_path
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolError, MaxToolFatalError, MaxToolRetryableError, MaxToolTransientError
from ee.hogai.utils.types.base import NodePath


class DummyToolInput(BaseModel):
    input_value: str


class DummyTool(MaxTool):
    name: str = "read_taxonomy"
    description: str = "A test tool for node_path testing"
    args_schema: type[BaseModel] = DummyToolInput

    async def _arun_impl(self, input_value: str):
        return ("result", {})


class TestMaxTool(BaseTest):
    def test_format_context_prompt_injection_no_template(self):
        tool = DummyTool(team=self.team, user=self.user)
        result = tool.format_context_prompt_injection({})
        assert result is None

    def test_format_context_prompt_injection(self):
        tool = DummyTool(team=self.team, user=self.user, context_prompt_template="Test")
        result = tool.format_context_prompt_injection({})
        assert result == "Test"

    def test_format_context_prompt_injection_missing_key_defaults_to_none(self):
        tool = DummyTool(team=self.team, user=self.user, context_prompt_template="Value: {expected_key}")
        result = tool.format_context_prompt_injection({})
        assert result == "Value: None"


class TestMaxToolNodePath(BaseTest):
    def test_node_path_uses_context_when_not_passed(self):
        context_path = (
            NodePath(name="parent_node"),
            NodePath(name="child_node"),
        )

        with set_node_path(context_path):
            tool = DummyTool(team=self.team, user=self.user)

            result = tool.node_path

            self.assertEqual(len(result), 3)
            self.assertEqual(result[0].name, "parent_node")
            self.assertEqual(result[1].name, "child_node")
            self.assertEqual(result[2].name, "max_tool.read_taxonomy")

    def test_node_path_uses_empty_tuple_when_no_context(self):
        tool = DummyTool(team=self.team, user=self.user, node_path=None)

        result = tool.node_path

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "max_tool.read_taxonomy")

    def test_node_path_uses_provided_path(self):
        provided_path = (
            NodePath(name="explicit_parent"),
            NodePath(name="explicit_child"),
        )

        tool = DummyTool(team=self.team, user=self.user, node_path=provided_path)

        result = tool.node_path

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].name, "explicit_parent")
        self.assertEqual(result[1].name, "explicit_child")
        self.assertEqual(result[2].name, "max_tool.read_taxonomy")


class TestMaxToolErrorHierarchy(BaseTest):
    """Test the MaxToolError exception hierarchy and retry strategies."""

    def test_max_tool_error_base_has_never_retry_strategy(self):
        """Base MaxToolError should have 'never' retry strategy."""
        error = MaxToolError("Base error message")
        self.assertEqual(error.retry_strategy, "never")
        self.assertEqual(str(error), "Base error message")

    def test_max_tool_error_base_has_no_retry_hint(self):
        """Base MaxToolError should have empty retry hint."""
        error = MaxToolError("Base error message")
        self.assertEqual(error.retry_hint, "")

    def test_max_tool_fatal_error_has_never_retry_strategy(self):
        """MaxToolFatalError should have 'never' retry strategy."""
        error = MaxToolFatalError("Fatal error: missing configuration")
        self.assertEqual(error.retry_strategy, "never")
        self.assertEqual(error.retry_hint, "")
        self.assertEqual(str(error), "Fatal error: missing configuration")

    def test_max_tool_transient_error_has_once_retry_strategy(self):
        """MaxToolTransientError should have 'once' retry strategy."""
        error = MaxToolTransientError("Rate limit exceeded")
        self.assertEqual(error.retry_strategy, "once")
        self.assertEqual(error.retry_hint, " You may retry this operation once without changes.")
        self.assertEqual(str(error), "Rate limit exceeded")

    def test_max_tool_retryable_error_has_adjusted_retry_strategy(self):
        """MaxToolRetryableError should have 'adjusted' retry strategy."""
        error = MaxToolRetryableError("Invalid parameter: entity kind must be 'person' or 'session'")
        self.assertEqual(error.retry_strategy, "adjusted")
        self.assertEqual(error.retry_hint, " You may retry with adjusted inputs.")
        self.assertEqual(str(error), "Invalid parameter: entity kind must be 'person' or 'session'")

    def test_error_inheritance_hierarchy(self):
        """All error types should inherit from MaxToolError and Exception."""
        fatal = MaxToolFatalError("fatal")
        transient = MaxToolTransientError("transient")
        retryable = MaxToolRetryableError("retryable")

        # Check inheritance
        self.assertIsInstance(fatal, MaxToolError)
        self.assertIsInstance(fatal, Exception)
        self.assertIsInstance(transient, MaxToolError)
        self.assertIsInstance(transient, Exception)
        self.assertIsInstance(retryable, MaxToolError)
        self.assertIsInstance(retryable, Exception)

    def test_errors_can_be_caught_as_max_tool_error(self):
        """All error types should be catchable as MaxToolError."""
        errors = [
            MaxToolFatalError("fatal"),
            MaxToolTransientError("transient"),
            MaxToolRetryableError("retryable"),
        ]

        for error in errors:
            try:
                raise error
            except MaxToolError as e:
                self.assertIsInstance(e, MaxToolError)
                self.assertIn(e.retry_strategy, ["never", "once", "adjusted"])

    def test_error_message_preservation(self):
        """Error messages should be preserved through the exception."""
        test_message = "This is a detailed error message with context about what went wrong"

        fatal = MaxToolFatalError(test_message)
        transient = MaxToolTransientError(test_message)
        retryable = MaxToolRetryableError(test_message)

        self.assertEqual(str(fatal), test_message)
        self.assertEqual(str(transient), test_message)
        self.assertEqual(str(retryable), test_message)

    def test_retry_hint_for_all_strategies(self):
        """Each retry strategy should have appropriate retry hint."""
        never_error = MaxToolFatalError("fatal")
        once_error = MaxToolTransientError("transient")
        adjusted_error = MaxToolRetryableError("retryable")

        # Never retry should have no hint
        self.assertEqual(never_error.retry_hint, "")

        # Once retry should suggest trying once
        self.assertIn("once", once_error.retry_hint.lower())
        self.assertIn("without changes", once_error.retry_hint.lower())

        # Adjusted retry should suggest adjusting inputs
        self.assertIn("adjusted", adjusted_error.retry_hint.lower())
        self.assertIn("inputs", adjusted_error.retry_hint.lower())

    def test_to_summary_formats_error_correctly(self):
        """to_summary() should format error with class name and message."""
        error = MaxToolFatalError("Something went wrong")
        summary = error.to_summary()

        self.assertEqual(summary, "MaxToolFatalError: Something went wrong")

    def test_to_summary_truncates_long_messages(self):
        """to_summary() should truncate messages longer than max_length."""
        long_message = "a" * 600
        error = MaxToolRetryableError(long_message)
        summary = error.to_summary(max_length=500)

        self.assertEqual(len(summary), 524)  # "MaxToolRetryableError: " (24) + 500 + "…" (1) = 525
        self.assertTrue(summary.startswith("MaxToolRetryableError: " + "a" * 500))
        self.assertTrue(summary.endswith("…"))

    def test_to_summary_respects_custom_max_length(self):
        """to_summary() should respect custom max_length parameter."""
        error = MaxToolTransientError("This is a medium length error message")
        summary = error.to_summary(max_length=20)

        self.assertTrue(summary.startswith("MaxToolTransientError: This is a medium len"))
        self.assertTrue(summary.endswith("…"))
        self.assertEqual(len(summary), 44)  # "MaxToolTransientError: " (23) + 20 + "…" (1) = 44

    def test_to_summary_strips_whitespace(self):
        """to_summary() should strip leading/trailing whitespace from messages."""
        error = MaxToolFatalError("  \n  Error with whitespace  \n  ")
        summary = error.to_summary()

        self.assertEqual(summary, "MaxToolFatalError: Error with whitespace")
