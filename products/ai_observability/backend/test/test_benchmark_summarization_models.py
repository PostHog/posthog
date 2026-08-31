import json
import tempfile
from pathlib import Path

import pytest
from unittest.mock import MagicMock

from django.core.management.base import CommandError

from parameterized import parameterized

from products.ai_observability.backend.management.commands.benchmark_summarization_models import (
    VARIANTS,
    Command,
    _call,
)
from products.ai_observability.backend.summarization.models import SummarizationMode

VALID_OUTPUT = json.dumps(
    {
        "title": "Test summary",
        "flow_diagram": "User -> Assistant",
        "summary_bullets": [{"text": "Test bullet", "line_refs": "L1"}],
        "interesting_notes": [],
    }
)


def _client(served_tier: str | None) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = 10_000
    usage.completion_tokens = 500
    usage.prompt_tokens_details.cached_tokens = 2_000
    usage.completion_tokens_details.reasoning_tokens = 300

    response = MagicMock()
    response.usage = usage
    response.service_tier = served_tier
    response.choices = [MagicMock()]
    response.choices[0].message.content = VALID_OUTPUT

    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


class TestBenchmarkCall:
    @parameterized.expand(
        [
            # 8000 uncached at 2.5e-8, 2000 cached at 2.5e-9, 500 output at 2e-7
            ("flex served as flex", "gpt5-nano-flex", "flex", 8_000 * 2.5e-8 + 2_000 * 2.5e-9 + 500 * 2e-7),
            # OpenAI declined flex, so the standard gpt-5-nano rate applies despite the request
            ("flex served as default", "gpt5-nano-flex", "default", 8_000 * 5e-8 + 2_000 * 5e-9 + 500 * 4e-7),
            ("baseline", "baseline", None, 8_000 * 1e-7 + 2_000 * 2.5e-8 + 500 * 4e-7),
        ]
    )
    def test_cost_uses_the_tier_openai_served(
        self, _name: str, variant_name: str, served_tier: str | None, expected_cost: float
    ) -> None:
        result = _call(
            client=_client(served_tier),
            variant=VARIANTS[variant_name],
            trace_id="trace-1",
            text_repr="L1: Test content",
            mode=SummarizationMode.MINIMAL,
            distinct_id="team-1",
        )

        assert result.ok
        assert result.cost_usd == expected_cost
        assert result.served_tier == served_tier
        assert result.reasoning_tokens == 300

    def test_trace_file_reduces_each_prompt_to_every_model_budget(self, tmp_path) -> None:
        path = tmp_path / "prompts.json"
        path.write_text(json.dumps([{"trace_id": "trace-1", "text_repr": "L1: x\n" * 200}]))

        trace_ids, text_reprs = Command()._load_trace_file(path, {50, 100_000})

        assert trace_ids == ["trace-1"]
        assert len(text_reprs[("trace-1", 50)]) <= 50
        assert text_reprs[("trace-1", 100_000)] == "L1: x\n" * 200

    @parameterized.expand(
        [
            ("not a list", json.dumps({"trace_id": "t"})),
            ("entry missing text_repr", json.dumps([{"trace_id": "t"}])),
            ("malformed json", "{not json"),
        ]
    )
    def test_a_bad_trace_file_fails_with_a_message(self, _name: str, contents: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompts.json"
            path.write_text(contents)
            with pytest.raises(CommandError):
                Command()._load_trace_file(path, {1_000})

    def test_a_failed_call_is_recorded_rather_than_raised(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("upstream refused")

        result = _call(
            client=client,
            variant=VARIANTS["gpt5-nano-flex"],
            trace_id="trace-1",
            text_repr="L1: Test content",
            mode=SummarizationMode.MINIMAL,
            distinct_id="team-1",
        )

        assert not result.ok
        assert result.error is not None
        assert "upstream refused" in result.error
