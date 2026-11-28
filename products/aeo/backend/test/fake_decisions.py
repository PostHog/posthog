from collections.abc import Callable, Mapping

from posthog.llm.system_one import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    JsonValue,
    NoulAnswer,
    Question,
    SystemOneRequestFailed,
    SystemOneResult,
)


class FakeDecisionModel:
    """Stands in for the gateway's System One client. `score` reads the item text each question points at and
    returns a yes-probability, or the chosen option for a choice question. `failures` are raised first, in order."""

    def __init__(
        self,
        score: Callable[[str], float | str],
        *,
        failures: list[SystemOneRequestFailed] | None = None,
    ) -> None:
        self._score = score
        self._failures = list(failures or [])
        self.requests: list[dict[str, JsonValue]] = []

    def decide(self, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        assert isinstance(state, dict)
        self.requests.append(state)
        if self._failures:
            raise self._failures.pop(0)
        answers: dict[str, Answer] = {}
        for question_id, question in questions.items():
            item_key = next(key for key in state if isinstance(state[key], dict) and question_id in state[key])
            text = state[item_key][question_id]
            verdict = self._score(str(text))
            if isinstance(question, ChoiceQuestion):
                choice = str(verdict)
                probabilities = {option: (0.9 if option == choice else 0.1) for option in question.criteria}
                answers[question_id] = ChoiceAnswer(choice=choice, confidence=0.9, probabilities=probabilities)
            else:
                answers[question_id] = NoulAnswer(probability=float(verdict))
        return SystemOneResult(model="fake", answers=answers, input_tokens=10 * len(questions))
