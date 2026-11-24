from typing import Any

import pytest

from parameterized import parameterized

from products.alerts.backend.judge.lazy_and import LazyAndEnsemble, split_ai_member

ZSCORE = {"type": "zscore", "window": 56}
MAD = {"type": "mad", "window": 30}
LLM = {"type": "llm"}


@parameterized.expand(
    [
        ("no_ai_member", ZSCORE, LazyAndEnsemble(local=ZSCORE)),
        (
            "local_ensemble_without_ai",
            {"type": "ensemble", "operator": "or", "detectors": [ZSCORE, MAD]},
            LazyAndEnsemble(local={"type": "ensemble", "operator": "or", "detectors": [ZSCORE, MAD]}),
        ),
        (
            "one_local_member_runs_alone",
            {"type": "ensemble", "operator": "and", "detectors": [ZSCORE, LLM]},
            LazyAndEnsemble(local=ZSCORE, judge=LLM),
        ),
        (
            "two_local_members_stay_an_ensemble",
            {"type": "ensemble", "operator": "and", "detectors": [ZSCORE, LLM, MAD]},
            LazyAndEnsemble(local={"type": "ensemble", "operator": "and", "detectors": [ZSCORE, MAD]}, judge=LLM),
        ),
    ]
)
def test_an_ai_member_is_split_from_the_local_part(
    _name: str, config: dict[str, Any], expected: LazyAndEnsemble
) -> None:
    assert split_ai_member(config) == expected


@parameterized.expand(
    [
        ("or_would_call_on_every_check", {"type": "ensemble", "operator": "or", "detectors": [ZSCORE, LLM]}),
        ("two_ai_members", {"type": "ensemble", "operator": "and", "detectors": [ZSCORE, LLM, LLM]}),
        ("no_local_member", {"type": "ensemble", "operator": "and", "detectors": [LLM, LLM]}),
        ("ai_alone", LLM),
    ]
)
def test_an_ensemble_that_would_call_the_model_without_a_local_flag_is_refused(
    _name: str, config: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        split_ai_member(config)
