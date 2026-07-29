import json
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import exceptions

from products.ai_observability.backend.summarization.constants import (
    EVALUATION_SUMMARY_CHUNK_SIZE,
    EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS,
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

    def test_large_run_set_bounds_map_requests_and_preserves_singleton_candidates(self):
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
                    "fail_patterns": [
                        {
                            "title": "Unsupported claims",
                            "description": "Failing responses made factual claims without supporting evidence.",
                            "frequency": "common",
                            "example_reasoning": "The factual claim has no citation.",
                            "example_generation_ids": ["g0", f"g{EVALUATION_SUMMARY_CHUNK_SIZE}"],
                        }
                    ],
                    "na_patterns": [],
                    "recommendations": ["Require citations for factual claims."],
                    "statistics": {"total_analyzed": 0, "pass_count": 0, "fail_count": 0, "na_count": 0},
                }
            )
        )

        run_count = EVALUATION_SUMMARY_CHUNK_SIZE + 1
        runs = [
            {
                "generation_id": f"g{i}",
                "result": False if i in {0, EVALUATION_SUMMARY_CHUNK_SIZE} else True,
                "reasoning": "The factual claim has no citation."
                if i in {0, EVALUATION_SUMMARY_CHUNK_SIZE}
                else f"Distinct passing theme {i}. " * 500,
            }
            for i in range(run_count)
        ]

        def completion_response(**kwargs) -> MagicMock:
            schema_name = kwargs["response_format"]["json_schema"]["name"]
            if schema_name == "evaluation_summary":
                return merged_response

            user_prompt = kwargs["messages"][1]["content"]
            patterns = []
            if "- Generation ID: g0\n" in user_prompt:
                patterns.append(
                    {
                        "result": "fail",
                        "title": "Missing citations",
                        "occurrence_count": 1,
                        "example_reasoning": "The factual claim has no citation.",
                        "example_generation_ids": ["g0"],
                    }
                )
            if f"- Generation ID: g{EVALUATION_SUMMARY_CHUNK_SIZE}\n" in user_prompt:
                patterns.append(
                    {
                        "result": "fail",
                        "title": "Unsupported claims",
                        "occurrence_count": 1,
                        "example_reasoning": "No source supports the factual claim.",
                        "example_generation_ids": [f"g{EVALUATION_SUMMARY_CHUNK_SIZE}"],
                    }
                )
            return response_with_content(json.dumps({"patterns": patterns}))

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

        map_calls = mock_client.chat.completions.create.await_args_list[:-1]
        assert len(map_calls) >= 3
        for map_call in map_calls:
            user_prompt = map_call.kwargs["messages"][1]["content"]
            response_schema = map_call.kwargs["response_format"]["json_schema"]["schema"]
            candidate_properties = response_schema["$defs"]["EvaluationPatternCandidate"]["properties"]

            assert len(user_prompt) <= EVALUATION_SUMMARY_MAP_PROMPT_MAX_CHARS
            assert response_schema["properties"]["patterns"]["maxItems"] == user_prompt.count("- Generation ID:")
            assert candidate_properties["occurrence_count"]["maximum"] == user_prompt.count("- Generation ID:")
            assert "maxLength" in candidate_properties["title"]
            assert "maxLength" in candidate_properties["example_reasoning"]
            assert "maxItems" in candidate_properties["example_generation_ids"]

        merge_user_prompt = mock_client.chat.completions.create.await_args_list[-1].kwargs["messages"][1]["content"]
        assert merge_user_prompt.count('"occurrence_count": 1') == 2
        assert '"g0"' in merge_user_prompt
        assert f'"g{EVALUATION_SUMMARY_CHUNK_SIZE}"' in merge_user_prompt
        assert f'"total_analyzed": {run_count}' in merge_user_prompt
        assert result.statistics.total_analyzed == run_count
        assert result.statistics.pass_count == run_count - 2
        assert result.statistics.fail_count == 2
