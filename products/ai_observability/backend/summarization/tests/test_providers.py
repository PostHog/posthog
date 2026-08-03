import re
import json
import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import exceptions

from products.ai_observability.backend.summarization.constants import (
    EVALUATION_SUMMARY_MAX_RUNS,
    EVALUATION_SUMMARY_PROMPT_MAX_CHARS,
    SUMMARIZATION_TIMEOUT,
)
from products.ai_observability.backend.summarization.llm.evaluation_summary import summarize_evaluation_runs
from products.ai_observability.backend.summarization.llm.openai import summarize_with_openai
from products.ai_observability.backend.summarization.llm.schema import SummarizationResponse
from products.ai_observability.backend.summarization.models import OpenAIModel, SummarizationMode


@pytest.fixture
def valid_response_json():
    return json.dumps(
        {
            "title": "Test Summary",
            "flow_diagram": "User -> Assistant",
            "summary_bullets": [{"text": "Test bullet", "line_refs": "L1"}],
            "interesting_notes": [],
        }
    )


class TestSummarizeWithOpenAI:
    def test_successful_summarization(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            result = summarize_with_openai(
                text_repr="L1: Test content",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            assert isinstance(result, SummarizationResponse)
            assert result.title == "Test Summary"
            mock_get_client.assert_called_once_with("llma_summarization", ai_product="aio_summarization")

    def test_empty_response_raises_validation_error(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_api_error_raises_api_exception(self):
        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API Error")

            with pytest.raises(exceptions.APIException, match="Failed to generate summary"):
                summarize_with_openai(
                    text_repr="L1: Test",
                    team_id=1,
                    mode=SummarizationMode.MINIMAL,
                    model=OpenAIModel.GPT_4_1_MINI,
                )

    def test_uses_correct_model(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == OpenAIModel.GPT_4_1_MINI

    def test_uses_user_id_when_provided(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
                user_id="user-distinct-123",
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "user-distinct-123"

    def test_uses_team_fallback_when_no_user_id(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=42,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["user"] == "team-42"

    def test_uses_json_schema_format(self, valid_response_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_response_json

        with patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            summarize_with_openai(
                text_repr="L1: Test",
                team_id=1,
                mode=SummarizationMode.MINIMAL,
                model=OpenAIModel.GPT_4_1_MINI,
            )

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["response_format"]["type"] == "json_schema"
            assert call_kwargs["response_format"]["json_schema"]["strict"] is True


@pytest.fixture
def valid_evaluation_summary_json():
    return json.dumps(
        {
            "overall_assessment": "Mostly passing.",
            "pass_patterns": [],
            "fail_patterns": [],
            "na_patterns": [],
            "recommendations": [],
            "statistics": {"total_analyzed": 1, "pass_count": 1, "fail_count": 0, "na_count": 0},
        }
    )


class TestSummarizeEvaluationRuns:
    def test_routes_through_async_gateway_builder_and_passes_timeout(self, valid_evaluation_summary_json):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_evaluation_summary_json

        with patch(
            "products.ai_observability.backend.summarization.llm.evaluation_summary.build_async_openai_client"
        ) as mock_builder:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_builder.return_value = mock_client

            result = asyncio.run(
                summarize_evaluation_runs(
                    evaluation_runs=[{"generation_id": "g1", "result": True, "reasoning": "good"}],
                    team_id=1,
                    model=OpenAIModel.GPT_4_1_MINI,
                )
            )

        mock_builder.assert_called_once_with("llma_eval_summary", ai_product="aio_eval_summary")
        assert mock_client.chat.completions.create.call_args.kwargs["timeout"] == SUMMARIZATION_TIMEOUT
        assert result.overall_assessment == "Mostly passing."

    def test_concurrent_requests_are_limited_per_team(self, valid_evaluation_summary_json: str) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_evaluation_summary_json

        async def run_summaries() -> None:
            first_call_started = asyncio.Event()
            release_first_call = asyncio.Event()
            completion_count = 0

            async def completion(**_kwargs: Any) -> MagicMock:
                nonlocal completion_count
                completion_count += 1
                if completion_count == 1:
                    first_call_started.set()
                    await release_first_call.wait()
                return mock_response

            with patch(
                "products.ai_observability.backend.summarization.llm.evaluation_summary.build_async_openai_client"
            ) as mock_builder:
                mock_client = MagicMock()
                mock_client.chat.completions.create = AsyncMock(side_effect=completion)
                mock_builder.return_value = mock_client

                first_summary = asyncio.create_task(
                    summarize_evaluation_runs(
                        evaluation_runs=[{"generation_id": "g1", "result": True, "reasoning": "good"}],
                        team_id=1,
                        model=OpenAIModel.GPT_4_1_MINI,
                    )
                )
                await first_call_started.wait()

                try:
                    with pytest.raises(exceptions.Throttled, match="already being generated"):
                        await summarize_evaluation_runs(
                            evaluation_runs=[{"generation_id": "g2", "result": True, "reasoning": "also good"}],
                            team_id=1,
                            model=OpenAIModel.GPT_4_1_MINI,
                        )

                    different_team_result = await summarize_evaluation_runs(
                        evaluation_runs=[{"generation_id": "g3", "result": True, "reasoning": "good"}],
                        team_id=2,
                        model=OpenAIModel.GPT_4_1_MINI,
                    )
                    assert different_team_result.overall_assessment == "Mostly passing."
                finally:
                    release_first_call.set()
                    await first_summary

                assert mock_client.chat.completions.create.await_count == 2

        asyncio.run(run_summaries())

    def test_large_run_set_bounds_every_request_and_retries_incomplete_maps(self) -> None:
        def response_with_content(content: str) -> MagicMock:
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = content
            return response

        merged_response = response_with_content(
            json.dumps(
                {
                    "overall_assessment": "The only failures were unsupported factual claims.",
                    "pass_patterns": [],
                    "fail_patterns": [],
                    "na_patterns": [],
                    "recommendations": ["Require citations for factual claims."],
                    "statistics": {"total_analyzed": 0, "pass_count": 0, "fail_count": 0, "na_count": 0},
                }
            )
        )

        run_count = EVALUATION_SUMMARY_MAX_RUNS
        runs = [
            {
                "generation_id": f"g{i}",
                "result": i % 2 == 0,
                "reasoning": f"Distinct reasoning for run {i}. " + "r" * 2_000,
            }
            for i in range(run_count)
        ]

        returned_incomplete_map = False

        def completion_response(**kwargs: Any) -> MagicMock:
            nonlocal returned_incomplete_map
            schema_name = kwargs["response_format"]["json_schema"]["name"]
            if schema_name == "evaluation_summary":
                return merged_response

            user_prompt = kwargs["messages"][1]["content"]
            if schema_name == "evaluation_summary_candidates":
                if not returned_incomplete_map:
                    returned_incomplete_map = True
                    return response_with_content(json.dumps({"patterns": []}))

                prompt_runs = re.findall(r"- Generation ID: (.+)\n  Result: (PASS|FAIL|N/A)", user_prompt)
                return response_with_content(
                    json.dumps(
                        {
                            "patterns": [
                                {
                                    "result": {"PASS": "pass", "FAIL": "fail", "N/A": "na"}[result],
                                    "title": f"Theme for {generation_id}".ljust(60, "x"),
                                    "occurrence_count": 1,
                                    "example_reasoning": f"Reasoning for {generation_id}".ljust(240, "r"),
                                    "example_generation_ids": [generation_id],
                                }
                                for generation_id, result in prompt_runs
                            ]
                        }
                    )
                )

            candidates = json.loads(user_prompt.split("Candidate themes to consolidate:\n", 1)[1])
            reduced_candidates = []
            for result in ("pass", "fail", "na"):
                matching_candidates = [candidate for candidate in candidates if candidate["result"] == result]
                if matching_candidates:
                    representative = {
                        **matching_candidates[0],
                        "occurrence_count": sum(candidate["occurrence_count"] for candidate in matching_candidates),
                        "example_generation_ids": [
                            generation_id
                            for candidate in matching_candidates
                            for generation_id in candidate["example_generation_ids"]
                        ][:3],
                    }
                    reduced_candidates.append(representative)
            return response_with_content(json.dumps({"patterns": reduced_candidates}))

        with patch(
            "products.ai_observability.backend.summarization.llm.evaluation_summary.build_async_openai_client"
        ) as mock_builder:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=completion_response)
            mock_builder.return_value = mock_client

            result = asyncio.run(
                summarize_evaluation_runs(
                    evaluation_runs=runs,
                    team_id=1,
                    model=OpenAIModel.GPT_4_1_MINI,
                )
            )

        all_calls = mock_client.chat.completions.create.await_args_list
        map_calls = [
            call
            for call in all_calls
            if call.kwargs["response_format"]["json_schema"]["name"] == "evaluation_summary_candidates"
        ]
        reduce_calls = [
            call
            for call in all_calls
            if call.kwargs["response_format"]["json_schema"]["name"] == "evaluation_summary_reduced_candidates"
        ]

        assert returned_incomplete_map
        assert len(map_calls) == len({call.kwargs["messages"][1]["content"] for call in map_calls}) + 1
        assert reduce_calls
        for completion_call in all_calls:
            messages = completion_call.kwargs["messages"]
            assert sum(len(message["content"]) for message in messages) <= EVALUATION_SUMMARY_PROMPT_MAX_CHARS

        for map_call in map_calls:
            user_prompt = map_call.kwargs["messages"][1]["content"]
            response_schema = map_call.kwargs["response_format"]["json_schema"]["schema"]
            candidate_properties = response_schema["$defs"]["EvaluationPatternCandidate"]["properties"]

            assert response_schema["properties"]["patterns"]["maxItems"] == user_prompt.count("- Generation ID:")
            assert candidate_properties["occurrence_count"]["maximum"] == user_prompt.count("- Generation ID:")
            assert "maxLength" in candidate_properties["title"]
            assert "maxLength" in candidate_properties["example_reasoning"]
            assert "maxItems" in candidate_properties["example_generation_ids"]

        merge_user_prompt = all_calls[-1].kwargs["messages"][1]["content"]
        assert f'"total_analyzed":{run_count}' in merge_user_prompt
        assert result.statistics.total_analyzed == run_count
        assert result.statistics.pass_count == run_count // 2
        assert result.statistics.fail_count == run_count // 2
