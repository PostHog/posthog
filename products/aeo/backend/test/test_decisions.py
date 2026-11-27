import pytest
from unittest.mock import patch

from posthog.llm.system_one import NoulQuestion, SystemOneRequestFailed

from products.aeo.backend import decisions
from products.aeo.backend.test.fake_decisions import FakeDecisionModel


class _NoWait:
    """A backoff that records its pauses instead of sleeping."""

    def __init__(self) -> None:
        self.pauses: list[float] = []

    def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)

    def wait(self) -> None:
        return None


def _ask(model: FakeDecisionModel) -> tuple[dict, list[decisions.DecisionUsage], _NoWait]:
    throttle = decisions._Throttle()
    backoff = _NoWait()
    usage: list[decisions.DecisionUsage] = []
    with (
        patch("products.aeo.backend.decisions.build_system_one_client", return_value=model),
        patch("products.aeo.backend.decisions.THROTTLE", throttle),
        patch.object(throttle, "backoff", backoff),
    ):
        answers = decisions.ask(
            team_id=1,
            feature="test",
            state={"items": {"i0": "a", "i1": "b"}},
            questions={"i0": NoulQuestion(instructions="`items.i0`?"), "i1": NoulQuestion(instructions="`items.i1`?")},
            usage=usage,
        )
    return dict(answers), usage, backoff


def test_a_throttled_request_pauses_every_worker_and_is_retried() -> None:
    model = FakeDecisionModel(
        lambda text: 0.9 if text == "a" else 0.1,
        failures=[SystemOneRequestFailed("busy", status_code=429)],
    )

    answers, usage, backoff = _ask(model)

    assert [answers["i0"].probability, answers["i1"].probability] == [0.9, 0.1]  # type: ignore[union-attr]
    assert backoff.pauses == [decisions.RETRY_BASE_SECONDS]
    assert (usage[0].requests, usage[0].throttled, usage[0].failed, usage[0].input_tokens) == (2, 1, 1, 20)


@pytest.mark.parametrize(
    "failures",
    [
        [SystemOneRequestFailed("bad request", status_code=400)],
        [SystemOneRequestFailed("busy", status_code=429)] * decisions.MAX_ATTEMPTS,
    ],
    ids=["not_retryable", "throttled_every_time"],
)
def test_a_request_without_a_usable_answer_raises_so_the_caller_falls_back(
    failures: list[SystemOneRequestFailed],
) -> None:
    model = FakeDecisionModel(lambda text: 0.5, failures=failures)

    with pytest.raises(decisions.DecisionError):
        _ask(model)
    assert len(model.requests) == len(failures), "a 400 is not retried; a 429 is retried until the attempts run out"
