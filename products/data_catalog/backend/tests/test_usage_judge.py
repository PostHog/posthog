from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.data_catalog.backend.facade.enums import JudgeRelation
from products.data_catalog.backend.logic.usage_judge import MetricBrief, judge_pair

METRIC = MetricBrief(name="signups", description="Weekly signups", definition="SELECT count() FROM events")


def _client(reply: str | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(reply, Exception):
        client.messages.create = AsyncMock(side_effect=reply)
    else:
        client.messages.create = AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])
        )
    return client


class TestJudgePair(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "fenced_json",
                '```json\n{"reasoning": "Same.", "relation": "slice", "confidence": 0.8}\n```',
                JudgeRelation.SLICE,
            ),
            (
                "unknown_relation",
                '{"reasoning": "Hm.", "relation": "maybe", "confidence": 0.5}',
                JudgeRelation.DIFFERENT,
            ),
            (
                "confidence_out_of_range",
                '{"reasoning": "Hm.", "relation": "serves", "confidence": 7}',
                JudgeRelation.DIFFERENT,
            ),
            ("not_json", "It serves the metric.", JudgeRelation.DIFFERENT),
            ("client_error", RuntimeError("gateway down"), JudgeRelation.DIFFERENT),
        ]
    )
    def test_only_a_valid_reply_can_match(self, _name: str, reply: str | Exception, relation: JudgeRelation) -> None:
        verdict = async_to_sync(judge_pair)(_client(reply), METRIC, "weekly signups", "select count() from events")

        assert verdict.relation == relation

    def test_prompt_carries_the_metric_the_intent_and_the_sql(self) -> None:
        client = _client('{"reasoning": "Same.", "relation": "serves", "confidence": 0.9}')

        async_to_sync(judge_pair)(client, METRIC, "signups per week", "SELECT uniq(person_id) FROM events")

        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        for expected in (
            "signups",
            "Weekly signups",
            "SELECT count() FROM events",
            "signups per week",
            "uniq(person_id)",
        ):
            assert expected in prompt
