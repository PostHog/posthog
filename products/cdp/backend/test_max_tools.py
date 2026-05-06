import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models.hog_functions.hog_function import HogFunction

from products.cdp.backend.max_tools import (
    CreateHogFunctionAction,
    CreateHogTransformationFunctionTool,
    UpdateHogFunctionAction,
    UpsertHogFunctionTool,
)

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException


class TestParseOutput:
    @parameterized.expand(
        [
            (
                "slice_syntax",
                "let x := content[1:2000]",
                "The Hog code failed to compile",
            ),
            (
                "double_ampersand",
                "if (a && b) { print(a) }",
                "no viable alternative at input",
            ),
        ]
    )
    def test_parse_output_includes_specific_parse_error(self, _name, hog_code, expected_fragment):
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert expected_fragment in str(exc_info.value)

    def test_parse_output_generic_error_for_non_syntax_issues(self):
        # Code that parses but fails at the HyphenatedPropertyDetector stage
        hog_code = "let x := event.some-prop"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert "The Hog code failed to compile" in str(exc_info.value)
        # Should NOT contain a specific parse error since it's not a syntax error
        assert "no viable alternative" not in str(exc_info.value)

    def test_parse_output_valid_code(self):
        hog_code = "let x := 1\nreturn event"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        result = tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert result.hog_code == hog_code


class TestUpsertHogFunctionTool(BaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(template_slack)
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _setup_tool(self) -> UpsertHogFunctionTool:
        return UpsertHogFunctionTool(team=self.team, user=self.user, config=self._config)

    def _alert_filter(self, alert_id: str) -> dict:
        return {
            "events": [{"id": "$insight_alert_firing", "type": "events"}],
            "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}],
        }

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_slack_destination_for_alert(self):
        tool = self._setup_tool()

        action = CreateHogFunctionAction(
            type="internal_destination",
            template_id="template-slack",
            name="Alert ABC → Slack",
            filters=self._alert_filter("alert-abc"),
            inputs={
                "slack_workspace": {"value": 1},
                "channel": {"value": "C0123ABC"},
                "text": {"value": "Alert triggered"},
            },
        )

        content, artifact = await tool._arun_impl(action=action)

        assert "created successfully" in content
        assert artifact["function_type"] == "internal_destination"
        assert artifact["enabled"] is True
        assert artifact["function_url"].startswith("/pipeline/destinations/hog-")

        function = await sync_to_async(HogFunction.objects.get)(id=artifact["function_id"])
        assert function.template_id == "template-slack"
        assert function.team == self.team
        assert function.filters["events"][0]["id"] == "$insight_alert_firing"
        assert function.filters["properties"][0]["value"] == "alert-abc"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_requires_template_or_hog(self):
        tool = self._setup_tool()
        action = CreateHogFunctionAction(type="destination", name="No source")

        content, artifact = await tool._arun_impl(action=action)

        assert "template_id or hog source" in content
        assert artifact["error"] == "validation_failed"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_changes_name_and_enabled(self):
        tool = self._setup_tool()

        _, create_artifact = await tool._arun_impl(
            action=CreateHogFunctionAction(
                type="internal_destination",
                template_id="template-slack",
                name="Old name",
                filters=self._alert_filter("alert-xyz"),
                inputs={
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "C0123ABC"},
                },
            )
        )

        function_id = create_artifact["function_id"]
        content, artifact = await tool._arun_impl(
            action=UpdateHogFunctionAction(function_id=function_id, name="New name", enabled=False)
        )

        assert "updated successfully" in content
        assert artifact["function_name"] == "New name"
        assert artifact["enabled"] is False

        function = await sync_to_async(HogFunction.objects.get)(id=function_id)
        assert function.name == "New name"
        assert function.enabled is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_with_no_fields_returns_error(self):
        tool = self._setup_tool()
        _, create_artifact = await tool._arun_impl(
            action=CreateHogFunctionAction(
                type="internal_destination",
                template_id="template-slack",
                name="Whatever",
                filters=self._alert_filter("alert-noop"),
                inputs={
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "C0123ABC"},
                },
            )
        )
        function_id = create_artifact["function_id"]

        content, artifact = await tool._arun_impl(action=UpdateHogFunctionAction(function_id=function_id))

        assert "No changes provided" in content
        assert artifact["error"] == "no_changes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_unknown_function_returns_not_found(self):
        tool = self._setup_tool()
        content, artifact = await tool._arun_impl(
            action=UpdateHogFunctionAction(function_id="00000000-0000-0000-0000-000000000000", name="Whatever")
        )
        assert "not found" in content
        assert artifact["error"] == "function_not_found"

    @parameterized.expand(
        [
            ("enabled_internal_destination", "internal_destination", "template-slack", True, True),
            ("disabled_internal_destination", "internal_destination", "template-slack", False, False),
            ("enabled_transformation", "transformation", None, True, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_for_create(
        self, _name: str, type: str, template_id: str | None, enabled: bool, expected: bool
    ):
        tool = self._setup_tool()
        action = CreateHogFunctionAction(
            type=type,
            template_id=template_id,
            hog="return event" if template_id is None else None,
            enabled=enabled,
        )
        assert await tool.is_dangerous_operation(action) is expected

    @pytest.mark.asyncio
    async def test_is_dangerous_operation_for_any_update(self):
        tool = self._setup_tool()
        action = UpdateHogFunctionAction(function_id="some-id", enabled=False)
        assert await tool.is_dangerous_operation(action) is True
