import json

from posthog.dataclasses import frozen

from ...facade.contracts import TraceNodeKind
from .event import kind_of_event
from .trace_queries import TraceNodeRow, read_flag, read_number, read_text

FAILED_STEP_MESSAGE = "This step failed."


@frozen
class IOKeyCandidates:
    input: tuple[str, ...]
    output: tuple[str, ...]
    tools: tuple[str, ...]


IO_KEY_CANDIDATES: dict[TraceNodeKind, IOKeyCandidates] = {
    "generation": IOKeyCandidates(
        input=("$ai_input",), output=("$ai_output_choices", "$ai_output"), tools=("$ai_tools",)
    ),
    "embedding": IOKeyCandidates(input=("$ai_input",), output=(), tools=()),
    "span": IOKeyCandidates(
        input=("$ai_input", "$ai_input_state"),
        output=("$ai_output_choices", "$ai_output_state", "$ai_output"),
        tools=(),
    ),
    "trace": IOKeyCandidates(
        input=("$ai_input_state", "$ai_input"),
        output=("$ai_output_state", "$ai_output_choices", "$ai_output"),
        tools=(),
    ),
}


@frozen
class IOKeys:
    input: str | None
    output: str | None
    tools: str | None


@frozen
class NodeMetadata:
    provider: str | None
    temperature: float | None
    session_id: str | None
    prompt_name: str | None
    prompt_version: float | None


@frozen
class NodeEvent:
    row: TraceNodeRow

    @property
    def kind(self) -> TraceNodeKind:
        return kind_of_event(self.row.event)

    @property
    def io_keys(self) -> IOKeys:
        candidates = IO_KEY_CANDIDATES[self.kind]
        return IOKeys(
            input=self._first_present(candidates.input),
            output=self._first_present(candidates.output),
            tools=self._first_present(candidates.tools),
        )

    @property
    def error(self) -> str | None:
        value = self.row.properties.get("$ai_error")
        if not value:
            return FAILED_STEP_MESSAGE if read_flag(self.row.properties.get("$ai_is_error")) else None
        return value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)

    @property
    def metadata(self) -> NodeMetadata:
        properties = self.row.properties
        return NodeMetadata(
            provider=read_text(properties.get("$ai_provider")),
            temperature=read_number(properties.get("$ai_temperature")),
            session_id=read_text(properties.get("$ai_session_id")),
            prompt_name=read_text(properties.get("$ai_prompt_name")),
            prompt_version=read_number(properties.get("$ai_prompt_version")),
        )

    def _first_present(self, keys: tuple[str, ...]) -> str | None:
        return next((key for key in keys if self.row.properties.get(key) is not None), None)
