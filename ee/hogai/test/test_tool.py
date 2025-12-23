from posthog.test.base import BaseTest
from unittest.mock import patch

from pydantic import BaseModel

from posthog.rbac.user_access_control import UserAccessControl

from ee.hogai.core.context import set_node_path
from ee.hogai.registry import CONTEXTUAL_TOOL_NAME_TO_TOOL, _import_max_tools
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import (
    MaxToolAccessDeniedError,
    MaxToolError,
    MaxToolFatalError,
    MaxToolRetryableError,
    MaxToolTransientError,
)
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


class TestMaxToolAccessDeniedError(BaseTest):
    """Test the MaxToolAccessDeniedError exception."""

    def test_access_denied_error_formats_correctly(self):
        """Access denied error should format correctly."""
        error = MaxToolAccessDeniedError("feature_flag", "editor")
        self.assertIn("editor", str(error))
        self.assertIn("feature_flag", str(error))
        self.assertIn("contact their project admin", str(error))
        self.assertEqual(error.resource, "feature_flag")
        self.assertEqual(error.required_level, "editor")

    def test_access_denied_error_with_custom_action(self):
        """Access denied error with custom action should format correctly."""
        error = MaxToolAccessDeniedError("dashboard", "editor", action="create")
        self.assertIn("create", str(error))
        self.assertIn("dashboard", str(error))

    def test_access_denied_is_fatal_error(self):
        """Access denied error should be a fatal error with 'never' retry strategy."""
        error = MaxToolAccessDeniedError("feature_flag", "editor")
        self.assertIsInstance(error, MaxToolFatalError)
        self.assertEqual(error.retry_strategy, "never")


class ToolWithAccessControlTool(MaxTool):
    """Test tool with access control requirements."""

    name: str = "create_feature_flag"
    description: str = "A test tool with access control"
    args_schema: type[BaseModel] = DummyToolInput

    def get_required_resource_access(self):
        return [("feature_flag", "editor")]

    async def _arun_impl(self, input_value: str):
        return ("result", {})


class ToolWithNoAccessControlTool(MaxTool):
    """Test tool without access control requirements."""

    name: str = "read_taxonomy"
    description: str = "A test tool without access control"
    args_schema: type[BaseModel] = DummyToolInput

    def get_required_resource_access(self):
        return []

    async def _arun_impl(self, input_value: str):
        return ("result", {})


class TestMaxToolAccessControl(BaseTest):
    """Test the MaxTool resource-level access control functionality."""

    def test_access_control_property_returns_user_access_control(self):
        """access_control property should return UserAccessControl instance."""
        tool = DummyTool(team=self.team, user=self.user)
        access_control = tool.user_access_control
        self.assertIsInstance(access_control, UserAccessControl)

    def test_get_required_resource_access_default_returns_empty(self):
        """Default get_required_resource_access should return empty list."""
        tool = DummyTool(team=self.team, user=self.user)
        self.assertEqual(tool.get_required_resource_access(), [])

    def test_get_required_resource_access_can_be_overridden(self):
        """get_required_resource_access can be overridden to return requirements."""
        tool = ToolWithAccessControlTool(team=self.team, user=self.user)
        requirements = tool.get_required_resource_access()
        self.assertEqual(requirements, [("feature_flag", "editor")])

    def test_check_access_control_passes_when_user_has_access(self):
        """_check_access_control should pass when user has required access."""
        tool = ToolWithAccessControlTool(team=self.team, user=self.user)

        with patch.object(tool.user_access_control, "check_access_level_for_resource", return_value=True):
            # Should not raise
            tool._check_access_control()

    def test_check_access_control_raises_when_user_lacks_access(self):
        """_check_access_control should raise MaxToolAccessDeniedError when user lacks access."""
        tool = ToolWithAccessControlTool(team=self.team, user=self.user)

        with patch.object(tool.user_access_control, "check_access_level_for_resource", return_value=False):
            with self.assertRaises(MaxToolAccessDeniedError) as ctx:
                tool._check_access_control()

            self.assertEqual(ctx.exception.resource, "feature_flag")
            self.assertEqual(ctx.exception.required_level, "editor")

    def test_check_access_control_skips_when_no_requirements(self):
        """_check_access_control should skip when get_required_resource_access returns empty list."""
        tool = ToolWithNoAccessControlTool(team=self.team, user=self.user)

        # Should not call check_access_level_for_resource at all
        with patch.object(tool.user_access_control, "check_access_level_for_resource") as mock:
            tool._check_access_control()
            mock.assert_not_called()


class TestToolAccessControlDeclarations(BaseTest):
    """
    Test that all tools declare their access control requirements.

    New tools MUST either:
    1. Implement get_required_resource_access() returning non-empty list, OR
    2. Be explicitly added to TOOLS_WITHOUT_ACCESS_CONTROL with a reason
    """

    # Tools that are explicitly exempt from access control.
    # Add a comment explaining WHY the tool doesn't need access control.
    TOOLS_WITHOUT_ACCESS_CONTROL: set[str] = {
        # Tools that don't view or modify protected resources
        "search",
        "read_taxonomy",
        "create_form",
        "todo_write",
        "switch_mode",
        "session_summarization",
        # Tools with dynamic/conditional access checks inside _arun_impl
        "read_data",
        # TODO: Add access control to these tools
        "task",
        "create_task",
        "run_task",
        "get_task_run",
        "get_task_run_logs",
        "list_tasks",
        "list_task_runs",
        "list_repositories",
        "create_message_template",
        "create_hog_function_inputs",
        "create_hog_transformation_function",
        "create_hog_function_filters",
        "execute_sql",
        "generate_hogql_query",
        "fix_hogql_query",
        "analyze_user_interviews",
    }

    def test_all_tools_have_access_control_or_are_exempt(self):
        """All tools must declare access control or be explicitly exempt."""
        _import_max_tools()

        missing_access_control = []
        for tool_name, tool_class in CONTEXTUAL_TOOL_NAME_TO_TOOL.items():
            if tool_name.value in self.TOOLS_WITHOUT_ACCESS_CONTROL:
                continue

            # Check that get_required_resource_access() is implemented
            tool_instance = tool_class(team=self.team, user=self.user, description="Test description")
            required_access = tool_instance.get_required_resource_access()

            if not required_access:
                missing_access_control.append(tool_name)

        if missing_access_control:
            self.fail(
                f"Tools without access control declaration: {missing_access_control}. "
                f"Either add get_required_resource_access() or add to TOOLS_WITHOUT_ACCESS_CONTROL with a reason."
            )
