import re
import json
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any, Literal, Optional, Union

from asgiref.sync import sync_to_async
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from rest_framework import serializers as drf_serializers

from posthog.hogql import errors as hogql_errors
from posthog.hogql.ai import (
    DESTINATION_LIMITATIONS_MESSAGE,
    EVENT_PROPERTY_TAXONOMY_MESSAGE,
    EVENT_TAXONOMY_MESSAGE,
    FILTER_TAXONOMY_MESSAGE,
    HOG_EXAMPLE_MESSAGE,
    HOG_FUNCTION_FILTERS_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_SYSTEM_PROMPT,
    HOG_GRAMMAR_MESSAGE,
    IDENTITY_MESSAGE_HOG,
    INPUT_SCHEMA_TYPES_MESSAGE,
    PERSON_TAXONOMY_MESSAGE,
    TRANSFORMATION_LIMITATIONS_MESSAGE,
)
from posthog.hogql.parser import parse_program

from posthog.api.hog_function import HogFunctionSerializer
from posthog.cdp.validation import compile_hog
from posthog.exceptions_capture import capture_exception
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.cdp.backend.prompts import (
    HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT,
    HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT,
)

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool


class CreateHogTransformationFunctionArgs(BaseModel):
    instructions: str = Field(description="The instructions for what transformation to create.")


class HogTransformationOutput(BaseModel):
    hog_code: str


class CreateHogFunctionFiltersArgs(BaseModel):
    instructions: str = Field(description="The instructions for what filters to create.")


class HogFunctionFiltersOutput(BaseModel):
    filters: dict


class CreateHogTransformationFunctionTool(MaxTool):
    name: str = "create_hog_transformation_function"  # Must match a value in AssistantTool enum
    description: str = "Write or edit the hog code to create your desired function and apply it to the current editor"
    args_schema: type[BaseModel] = CreateHogTransformationFunctionArgs
    context_prompt_template: str = (
        HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT
        + "\n\n"
        + TRANSFORMATION_LIMITATIONS_MESSAGE
        + "\n\n"
        + DESTINATION_LIMITATIONS_MESSAGE
    )

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        current_hog_code = self.context.get("current_hog_code", "")

        system_content = (
            IDENTITY_MESSAGE_HOG
            + "\n\n<example_hog_code>\n"
            + HOG_EXAMPLE_MESSAGE
            + "\n</example_hog_code>\n\n"
            + "\n\n<hog_grammar>\n"
            + HOG_GRAMMAR_MESSAGE
            + "\n</hog_grammar>\n\n"
            + "\n\n<current_hog_code>\n"
            + current_hog_code
            + "\n</current_hog_code>"
            + "\n\nReturn ONLY the hog code inside <hog_code> tags. Do not add any other text or explanation."
        )

        user_content = "Write a Hog transformation or tweak the current one to satisfy this request: " + instructions

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        return "```hog\n" + parsed_result.hog_code + "\n```", parsed_result.hog_code

    @property
    def _model(self) -> BaseChatModel:
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
        )

    def _parse_output(self, output: str) -> HogTransformationOutput:
        match = re.search(r"<hog_code>(.*?)</hog_code>", output, re.DOTALL)
        if not match:
            # The model may have returned the code without tags, or with markdown
            hog_code = re.sub(
                r"^\s*```hog\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            hog_code = match.group(1).strip()

        if not hog_code:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty hog code response."
            )

        try:
            compile_hog(hog_code, "transformation")
        except Exception:
            # Try to get a more specific error by parsing directly
            try:
                parse_program(hog_code)
            except hogql_errors.SyntaxError as parse_err:
                raise PydanticOutputParserException(
                    llm_output=hog_code,
                    validation_message=f"The Hog code failed to compile: {parse_err}",
                )
            raise PydanticOutputParserException(
                llm_output=hog_code,
                validation_message="The Hog code failed to compile.",
            )

        return HogTransformationOutput(hog_code=hog_code)


class CreateHogFunctionFiltersTool(MaxTool):
    name: str = "create_hog_function_filters"  # Must match a value in AssistantTool enum
    description: str = (
        "Create or edit filters for hog functions to specify which events and properties trigger the function"
    )
    args_schema: type[BaseModel] = CreateHogFunctionFiltersArgs
    context_prompt_template: str = HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        current_filters = self.context.get("current_filters", "{}")
        function_type = self.context.get("function_type", "destination")

        system_content = (
            HOG_FUNCTION_FILTERS_SYSTEM_PROMPT
            + f"\n\nCurrent filters: {current_filters}"
            + f"\nFunction type: {function_type}"
            + "\n\n<event_taxonomy>\n"
            + EVENT_TAXONOMY_MESSAGE
            + "\n</event_taxonomy>\n\n"
            + "\n\n<event_property_taxonomy>\n"
            + EVENT_PROPERTY_TAXONOMY_MESSAGE
            + "\n</event_property_taxonomy>\n\n"
            + "\n\n<person_property_taxonomy>\n"
            + PERSON_TAXONOMY_MESSAGE
            + "\n</person_property_taxonomy>\n\n"
            + "\n\n<filter_taxonomy>\n"
            + FILTER_TAXONOMY_MESSAGE
            + "\n</filter_taxonomy>"
        )

        user_content = f"Create filters for this hog function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        return (
            f"```json\n{json.dumps(parsed_result.filters, indent=2)}\n```",
            json.dumps(parsed_result.filters),
        )

    @property
    def _model(self) -> BaseChatModel:
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
        )

    def _parse_output(self, output: str) -> HogFunctionFiltersOutput:
        match = re.search(r"<filters>(.*?)</filters>", output, re.DOTALL)
        if not match:
            # The model may have returned the JSON without tags, or with markdown
            json_str = re.sub(
                r"^\s*```json\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            json_str = match.group(1).strip()

        if not json_str:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty filters response."
            )

        try:
            filters = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The filters JSON failed to parse: {str(e)}"
            )

        return HogFunctionFiltersOutput(filters=filters)


class CreateHogFunctionInputsArgs(BaseModel):
    instructions: str = Field(description="The instructions for what inputs to generate or modify.")


class HogFunctionInputsOutput(BaseModel):
    inputs_schema: list = Field(description="The generated inputs schema for the hog function")


class CreateHogFunctionInputsTool(MaxTool):
    name: str = "create_hog_function_inputs"
    description: str = "Generate or modify input variables for hog functions based on the current code and requirements"
    args_schema: type[BaseModel] = CreateHogFunctionInputsArgs
    context_prompt_template: str = HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, list]:
        current_inputs_schema = self.context.get("current_inputs_schema", [])
        hog_code = self.context.get("hog_code", "")

        system_content = (
            HOG_FUNCTION_INPUTS_SYSTEM_PROMPT
            + f"\n\nCurrent hog code:\n{hog_code}"
            + f"\nCurrent inputs schema:\n{current_inputs_schema}"
            + "\n\n<input_schema_types>\n"
            + INPUT_SCHEMA_TYPES_MESSAGE
            + "\n</input_schema_types>"
        )

        user_content = f"Create or modify the input variables for this function: {instructions}"

        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[BaseException] = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                assert isinstance(result.content, str)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        # Format the output for display
        import json

        formatted_json = json.dumps(parsed_result.inputs_schema, indent=2)
        return f"```json\n{formatted_json}\n```", parsed_result.inputs_schema

    @property
    def _model(self) -> BaseChatModel:
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
        )

    def _parse_output(self, output: str) -> HogFunctionInputsOutput:
        import json

        match = re.search(r"<inputs_schema>(.*?)</inputs_schema>", output, re.DOTALL)
        if not match:
            # Try to find JSON array in the output
            json_match = re.search(r"\[[\s\S]*\]", output)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise PydanticOutputParserException(
                    llm_output=output, validation_message="Could not find inputs_schema in the response."
                )
        else:
            json_str = match.group(1).strip()

        try:
            inputs_schema = json.loads(json_str)
            if not isinstance(inputs_schema, list):
                raise PydanticOutputParserException(
                    llm_output=output, validation_message="Inputs schema must be a list."
                )
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=output, validation_message=f"Invalid JSON in inputs schema: {str(e)}"
            )

        return HogFunctionInputsOutput(inputs_schema=inputs_schema)


# Function types whose enabled creates produce externally-visible side-effects and should require
# user approval. `destination` / `site_destination` / `internal_destination` push outbound traffic;
# `source_webhook` accepts incoming traffic on a registered URL; `site_app` injects JavaScript into
# every page load. `transformation` runs in-process during ingestion. `warehouse_source_webhook` is
# rejected entirely by HogFunctionSerializer.validate_type (posthog/api/hog_function.py:266) so it
# can never reach the dangerous-op gate; it is excluded from this set on purpose.
_EXTERNAL_SIDE_EFFECT_TYPES: frozenset[HogFunctionType] = frozenset(
    {
        HogFunctionType.DESTINATION,
        HogFunctionType.SITE_DESTINATION,
        HogFunctionType.INTERNAL_DESTINATION,
        HogFunctionType.SOURCE_WEBHOOK,
        HogFunctionType.SITE_APP,
    }
)

# Recipe payload + event property catalog shared with the MCP cdp-functions-create tool. Single
# source of truth — edit the markdown, not this constant. See `description_appendix_file` in
# products/cdp/mcp/cdp_functions.yaml for the MCP-side consumer. The file is read at import time
# but wrapped so a missing markdown degrades to a recipe-less description rather than killing the
# import graph (which would also disable unrelated tools in this module).
try:
    _INSIGHT_ALERT_DESTINATION_RECIPE = (
        Path(__file__).resolve().parent.parent / "recipes" / "insight_alert_destination.md"
    ).read_text(encoding="utf-8")
except FileNotFoundError:
    _INSIGHT_ALERT_DESTINATION_RECIPE = ""

_UPSERT_HOG_FUNCTION_PRELUDE = dedent(
    """
    Use this tool to create or update CDP functions: destinations, transformations, internal
    destinations (the type used to deliver insight alerts to Slack or webhooks), site destinations,
    site apps, and source webhooks. Functions can derive their code and inputs from a HogFunctionTemplate
    or be defined inline as Hog source.

    # Actions
    - **create**: Create a new function (requires `type`; either `template_id` or `hog` source).
    - **update**: Edit an existing function by `function_id` (any subset of fields).

    # Common payload shape
    - `type`: destination | site_destination | internal_destination | source_webhook | site_app | transformation
    - `template_id`: ID of the HogFunctionTemplate to derive defaults from (code, inputs_schema, icon,
      name, description). Required if `hog` is not provided on create.
    - `hog`: Source code for the function (Hog for most types; TypeScript for site_destination/site_app).
    - `inputs`: Mapping of input keys to {"value": ...} payloads. Must satisfy the template's inputs_schema.
    - `inputs_schema`: List of input parameter definitions. Defaults to the template's schema on create.
    - `filters`: Event filter dict with `events` and `properties` lists, e.g.
      `{"events": [{"id": "$pageview", "type": "events"}], "properties": []}`.
    - `enabled`: Whether the function is active and processes events (default true on create).
    - `name`, `description`: Display strings; default to the template's values on create.

    # Routing an insight alert to Slack or a webhook

    The `upsert_alert` tool only attaches an email subscription to the current user. To deliver firings
    to Slack or a webhook, after creating the alert with `upsert_alert` (to obtain `<alert_id>`):

    1. Gather destination details from the user — Max does not currently surface listings of
       configured integrations or existing destinations:
       - For Slack: ask the user for the Slack workspace integration's numeric ID and the channel id
         (e.g. `C0123ABC`) or `#channel-name`. Both are configured under their PostHog project's
         integration settings.
       - For webhook: the user provides the destination `https://` URL directly.

    2. Re-using vs creating: this tool does not list existing alert destinations. If the user asks to
       update existing Slack delivery for an alert, ask them for the `function_id` (visible at
       `/pipeline/destinations/`) and call this tool with `action=update`. When unsure, prefer asking
       over creating a second destination — duplicates would fire twice on every alert.
    """
).strip()

UPSERT_HOG_FUNCTION_TOOL_DESCRIPTION = f"{_UPSERT_HOG_FUNCTION_PRELUDE}\n\n{_INSIGHT_ALERT_DESTINATION_RECIPE.strip()}"


class CreateHogFunctionAction(BaseModel):
    action: Literal["create"] = "create"
    type: HogFunctionType = Field(
        description="Function type. internal_destination is the right choice for routing alerts to Slack/webhook."
    )
    name: str | None = Field(
        default=None,
        description="Display name. Defaults to the template's name when a template_id is provided.",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description. Defaults to the template's description when a template_id is provided.",
    )
    template_id: str | None = Field(
        default=None,
        description=(
            "ID of the HogFunctionTemplate to derive code, inputs_schema, icon, name, and description from. "
            "Use 'template-slack' or 'template-webhook' for alert delivery destinations."
        ),
    )
    hog: str | None = Field(
        default=None,
        description="Source code. Required if no template_id is provided. Hog for most types; TypeScript for site_destination/site_app.",
    )
    inputs: dict[str, Any] | None = Field(
        default=None,
        description='Mapping of input keys to {"value": ...} payloads. Must satisfy the inputs_schema of the function or template.',
    )
    inputs_schema: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional inputs schema override. When omitted on create with a template_id, the template's schema is used.",
    )
    filters: dict[str, Any] | None = Field(
        default=None,
        description="Event filter dict with `events` and `properties` lists controlling when the function runs.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the function is active and processing events.",
    )


class UpdateHogFunctionAction(BaseModel):
    action: Literal["update"] = "update"
    function_id: str = Field(description="The UUID of the function to update.")
    name: str | None = Field(default=None, description="New display name.")
    description: str | None = Field(default=None, description="New description.")
    hog: str | None = Field(default=None, description="New source code.")
    inputs: dict[str, Any] | None = Field(
        default=None, description='Replacement inputs mapping. Provide the full set of {"value": ...} payloads.'
    )
    inputs_schema: list[dict[str, Any]] | None = Field(default=None, description="Replacement inputs schema.")
    filters: dict[str, Any] | None = Field(default=None, description="Replacement event filter dict.")
    enabled: bool | None = Field(default=None, description="Enable or disable the function.")


UpsertHogFunctionAction = Union[CreateHogFunctionAction, UpdateHogFunctionAction]


class UpsertHogFunctionToolArgs(BaseModel):
    action: UpsertHogFunctionAction = Field(
        description="Either create a new HogFunction or update an existing one.",
        discriminator="action",
    )


class UpsertHogFunctionTool(MaxTool):
    name: str = "upsert_hog_function"
    description: str = UPSERT_HOG_FUNCTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpsertHogFunctionToolArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("hog_function", "editor")]

    async def is_dangerous_operation(self, action: UpsertHogFunctionAction, **kwargs) -> bool:
        if isinstance(action, UpdateHogFunctionAction):
            # No-op updates short-circuit to "no changes" before any external effect — don't waste
            # the user's approval on something that isn't going to do anything anyway.
            changes = action.model_dump(exclude={"action", "function_id"}, exclude_unset=True)
            return bool(changes)
        return action.enabled and action.type in _EXTERNAL_SIDE_EFFECT_TYPES

    async def format_dangerous_operation_preview(self, action: UpsertHogFunctionAction, **kwargs) -> str:
        if isinstance(action, UpdateHogFunctionAction):
            fn = await self._resolve_function(action.function_id)
            label = f"'{fn.name}'" if fn else f"(ID: {action.function_id})"
            changed_fields = sorted(action.model_dump(exclude={"action", "function_id"}, exclude_unset=True).keys())
            field_summary = f" — fields: {', '.join(f'`{f}`' for f in changed_fields)}" if changed_fields else ""
            return f"**Update** function {label}{field_summary}"

        name = action.name or action.template_id or action.type
        return f"**Create** {action.type} '{name}' (enabled — will start processing matching events immediately)"

    async def _arun_impl(self, action: UpsertHogFunctionAction) -> tuple[str, dict[str, Any]]:
        if isinstance(action, CreateHogFunctionAction):
            return await self._handle_create(action)
        return await self._handle_update(action)

    async def _handle_create(self, action: CreateHogFunctionAction) -> tuple[str, dict[str, Any]]:
        if not action.template_id and not action.hog:
            return "Either template_id or hog source must be provided to create a function.", {
                "error": "validation_failed",
            }

        data = action.model_dump(exclude={"action"}, exclude_unset=True)
        # `enabled` is omitted by exclude_unset when the caller relies on its True default. Force it
        # in so HogFunction's own model default (False) doesn't quietly leave the function disabled.
        data.setdefault("enabled", action.enabled)

        try:
            function = await sync_to_async(self._save_via_serializer)(data, instance=None)
        except drf_serializers.ValidationError as e:
            return f"Validation failed: {e.detail}", {"error": "validation_failed", "details": e.detail}
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create function: {str(e)}", {"error": "creation_failed", "details": str(e)}

        status = "enabled" if function.enabled else "disabled"
        artifact = self._artifact_for(function)
        message = (
            f"Function '{function.name}' created successfully and is {status}. "
            f"[View function]({artifact['function_url']})."
        )
        return message, artifact

    async def _handle_update(self, action: UpdateHogFunctionAction) -> tuple[str, dict[str, Any]]:
        function = await self._resolve_function(action.function_id)
        if function is None:
            return f"Function '{action.function_id}' not found.", {"error": "function_not_found"}

        await self.check_object_access(function, "editor", resource="hog_function", action="edit")

        data = action.model_dump(exclude={"action", "function_id"}, exclude_unset=True)
        if not data:
            return "No changes provided. Specify at least one field to update.", {"error": "no_changes"}

        try:
            function = await sync_to_async(self._save_via_serializer)(data, instance=function)
        except drf_serializers.ValidationError as e:
            return f"Validation failed: {e.detail}", {"error": "validation_failed", "details": e.detail}
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to update function: {str(e)}", {"error": "update_failed", "details": str(e)}

        artifact = self._artifact_for(function)
        return (
            f"Function '{function.name}' updated successfully. [View function]({artifact['function_url']}).",
            artifact,
        )

    @staticmethod
    def _artifact_for(function: HogFunction) -> dict[str, Any]:
        return {
            "function_id": str(function.id),
            "function_name": function.name,
            "function_url": function.get_file_system_representation().href,
            "function_type": function.type,
            "enabled": function.enabled,
        }

    def _save_via_serializer(self, data: dict[str, Any], *, instance: HogFunction | None) -> HogFunction:
        """Routing through the serializer (rather than ``HogFunction.objects.create``) is the blessed
        pattern: it resolves ``template_id`` against the template registry, fills in defaults from the
        template, compiles bytecode for ``hog`` and ``filters``, and runs all the per-field validators.

        ``HogFunctionSerializer.create`` reads ``self.context["request"].user`` to populate
        ``created_by``. Outside a DRF view we have no Request, so we satisfy the contract with a
        minimal stand-in carrying the calling user.
        """
        team = self._team
        context: dict[str, Any] = {
            "request": SimpleNamespace(user=self._user),
            "get_team": lambda: team,
            "is_create": instance is None,
        }
        serializer = HogFunctionSerializer(instance=instance, data=data, partial=instance is not None, context=context)
        serializer.is_valid(raise_exception=True)
        return serializer.save(team=team) if instance is None else serializer.save()

    async def _resolve_function(self, function_id: str) -> HogFunction | None:
        normalized = str(function_id).strip()
        if not normalized:
            return None
        try:
            return await HogFunction.objects.aget(id=normalized, team_id=self._team.id)
        except (HogFunction.DoesNotExist, ValueError):
            return None
