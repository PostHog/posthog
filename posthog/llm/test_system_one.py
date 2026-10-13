from parameterized import parameterized

from posthog.llm.system_one import (
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    RefusalAnswer,
    ScoreQuestion,
    parse_system_one_response,
)


@parameterized.expand(
    [
        ("noul", NoulQuestion(instructions="Urgent?")),
        ("choice", ChoiceQuestion(instructions="Which team?", criteria={"billing": None, "support": None})),
        ("score", ScoreQuestion(instructions="How severe?", criteria=["low", "high"])),
    ]
)
def test_a_refused_question_keeps_the_other_answers(_name: str, refused: Question) -> None:
    result = parse_system_one_response(
        {
            "model": "gpt-6-luna",
            "answers": {"refused": {"type": "refusal"}, "answered": {"type": "noul", "noul": 0.7}},
        },
        {"refused": refused, "answered": NoulQuestion(instructions="Polite?")},
    )

    assert result.answers == {"refused": RefusalAnswer(), "answered": NoulAnswer(probability=0.7)}
