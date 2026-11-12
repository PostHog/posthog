from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.traces.parser_verdict import parser_test_result
from products.ai_observability.backend.logic.traces.step_content import SideReading, StepReading

CONTENT = contracts.TraceNodeContent(
    input=contracts.TraceJsonSide(kind="json", value={"k": 1}),
    output=contracts.TraceMessagesSide(kind="messages", messages=[]),
)
RECOGNIZED = SideReading(recognized=True)
UNRECOGNIZED = SideReading(recognized=False)


def reading(input_side: SideReading, output_side: SideReading) -> StepReading:
    return StepReading(content=CONTENT, input=input_side, output=output_side)


def side(result: contracts.TraceParserTestSide) -> tuple[bool, bool]:
    return result.needed_fixing, result.fixed


@parameterized.expand(
    [
        ("the only unrecognized side is fixed", (UNRECOGNIZED, RECOGNIZED), (RECOGNIZED, RECOGNIZED), True),
        ("both sides fixed", (UNRECOGNIZED, UNRECOGNIZED), (RECOGNIZED, RECOGNIZED), True),
        ("one of two unrecognized sides fixed", (UNRECOGNIZED, UNRECOGNIZED), (RECOGNIZED, UNRECOGNIZED), False),
        ("nothing fixed", (UNRECOGNIZED, RECOGNIZED), (UNRECOGNIZED, RECOGNIZED), False),
        ("nothing needed fixing", (RECOGNIZED, RECOGNIZED), (RECOGNIZED, RECOGNIZED), False),
    ]
)
def test_passes_only_when_every_side_that_needed_fixing_is_fixed(_name, baseline, candidate, passed):
    result = parser_test_result(reading(*baseline), reading(*candidate))

    assert result.passed is passed
    assert side(result.input) == (not baseline[0].recognized, not baseline[0].recognized and candidate[0].recognized)
    assert side(result.output) == (not baseline[1].recognized, not baseline[1].recognized and candidate[1].recognized)


@parameterized.expand(
    [
        (
            "a failure without the candidate is the existing recipes'",
            SideReading(recognized=False, runtime_error="deadline"),
            SideReading(recognized=False, runtime_error="deadline"),
            contracts.TraceParserTestError(source="existing_recipes", message="deadline"),
        ),
        (
            "a failure only with the candidate is the candidate's",
            UNRECOGNIZED,
            SideReading(recognized=False, runtime_error="budget"),
            contracts.TraceParserTestError(source="candidate", message="budget"),
        ),
        ("no failure", UNRECOGNIZED, RECOGNIZED, None),
    ]
)
def test_a_runtime_failure_names_whose_recipes_failed(_name, baseline_input, candidate_input, error):
    result = parser_test_result(reading(baseline_input, RECOGNIZED), reading(candidate_input, RECOGNIZED))

    assert result.input.error == error
    assert result.output.error is None


def test_the_content_shown_is_the_candidates():
    candidate_content = contracts.TraceNodeContent(
        input=contracts.TraceMessagesSide(kind="messages", messages=[]),
        output=contracts.TraceMessagesSide(kind="messages", messages=[]),
    )

    result = parser_test_result(
        reading(UNRECOGNIZED, RECOGNIZED),
        StepReading(content=candidate_content, input=RECOGNIZED, output=RECOGNIZED),
    )

    assert result.content == candidate_content


@parameterized.expand(
    [
        ("with a runtime failure", SideReading(recognized=False, runtime_error="deadline"), "deadline"),
        ("without one", UNRECOGNIZED, None),
    ]
)
def test_a_parser_that_breaks_a_side_that_was_parsed_fails(_name, broken_output, message):
    result = parser_test_result(reading(UNRECOGNIZED, RECOGNIZED), reading(RECOGNIZED, broken_output))

    assert result.passed is False
    assert (result.output.needed_fixing, result.output.broken) == (False, True)
    assert result.output.error == (
        contracts.TraceParserTestError(source="candidate", message=message) if message is not None else None
    )
