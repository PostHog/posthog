from ...facade import contracts
from .step_content import SideReading, StepReading


def parser_test_result(baseline: StepReading, candidate: StepReading) -> contracts.TraceNodeParserTest:
    """Judges a parser by comparing a step read with the project's saved parsers to one with the parser added."""
    sides = (_side_result(baseline.input, candidate.input), _side_result(baseline.output, candidate.output))
    needing_fixes = [side for side in sides if side.needed_fixing]
    return contracts.TraceNodeParserTest(
        content=candidate.content,
        input=sides[0],
        output=sides[1],
        passed=bool(needing_fixes)
        and all(side.fixed for side in needing_fixes)
        and not any(side.broken for side in sides),
    )


def _side_result(baseline: SideReading, candidate: SideReading) -> contracts.TraceParserTestSide:
    return contracts.TraceParserTestSide(
        needed_fixing=not baseline.recognized,
        fixed=not baseline.recognized and candidate.recognized,
        broken=baseline.recognized and not candidate.recognized,
        error=_error(baseline, candidate),
    )


def _error(baseline: SideReading, candidate: SideReading) -> contracts.TraceParserTestError | None:
    if baseline.runtime_error is not None:
        return contracts.TraceParserTestError(source="existing_recipes", message=baseline.runtime_error)
    if candidate.runtime_error is not None:
        return contracts.TraceParserTestError(source="candidate", message=candidate.runtime_error)
    return None
