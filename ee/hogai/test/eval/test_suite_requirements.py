from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.harness.env_preflight import validate_eval_env
from ee.hogai.eval.sandboxed.harness.providers import PreflightError
from ee.hogai.eval.sandboxed.harness.requirements import INFRA_BY_KIND, Infra, SuiteKind, expand, infra_union

ALL_ENV_VARS = (
    "BRAINTRUST_API_KEY",
    "SANDBOX_JWT_PRIVATE_KEY",
    "LLM_GATEWAY_ANTHROPIC_API_KEY",
    "LLM_GATEWAY_OPENAI_API_KEY",
)


@pytest.mark.parametrize(
    "requested, expected",
    [
        pytest.param({Infra.DATABASE}, {Infra.DATABASE}, id="database_implies_nothing"),
        pytest.param(
            {Infra.MCP_SERVER},
            {Infra.MCP_SERVER, Infra.LIVE_SERVER, Infra.DATABASE},
            id="mcp_server_pulls_live_server_and_database",
        ),
        pytest.param(
            {Infra.DEMO_DATA},
            {Infra.DEMO_DATA, Infra.DATABASE, Infra.PERSONHOG},
            id="demo_data_pulls_database_and_personhog",
        ),
        pytest.param({Infra.SANDBOX}, set(Infra), id="sandbox_pulls_everything"),
    ],
)
def test_expand_closes_over_implications(requested: set[Infra], expected: set[Infra]) -> None:
    assert expand(requested) == frozenset(expected)


@pytest.mark.parametrize(
    "kinds, expected",
    [
        pytest.param([SuiteKind.SANDBOXED], set(Infra), id="sandboxed_needs_everything"),
        pytest.param(
            [SuiteKind.ONE_SHOT],
            {Infra.DATABASE, Infra.PERSONHOG, Infra.DEMO_DATA},
            id="one_shot_skips_servers_and_sandbox",
        ),
        pytest.param([SuiteKind.SANDBOXED, SuiteKind.ONE_SHOT], set(Infra), id="mixed_run_is_the_union"),
        pytest.param([], set(), id="no_kinds_no_infra"),
    ],
)
def test_infra_union(kinds: list[SuiteKind], expected: set[Infra]) -> None:
    assert infra_union(kinds) == frozenset(expected)


def test_every_kind_declares_a_closed_infra_set() -> None:
    for kind, infra in INFRA_BY_KIND.items():
        assert expand(infra) == infra, f"{kind} declares an infra set that is not implication-closed"


@pytest.mark.parametrize(
    "kinds, agent_runtime, env, expect_missing",
    [
        pytest.param(
            {SuiteKind.ONE_SHOT},
            "claude",
            {"BRAINTRUST_API_KEY": "x", "LLM_GATEWAY_ANTHROPIC_API_KEY": "x"},
            (),
            id="one_shot_run_needs_no_sandbox_credentials",
        ),
        pytest.param(
            {SuiteKind.ONE_SHOT},
            "claude",
            {"BRAINTRUST_API_KEY": "x"},
            ("LLM_GATEWAY_ANTHROPIC_API_KEY",),
            id="one_shot_run_still_needs_the_generation_key",
        ),
        pytest.param(
            {SuiteKind.SANDBOXED},
            "claude",
            {"BRAINTRUST_API_KEY": "x", "LLM_GATEWAY_ANTHROPIC_API_KEY": "x"},
            ("SANDBOX_JWT_PRIVATE_KEY",),
            id="sandboxed_run_needs_the_jwt_key",
        ),
        pytest.param(
            {SuiteKind.SANDBOXED, SuiteKind.ONE_SHOT},
            "claude",
            {"BRAINTRUST_API_KEY": "x"},
            ("SANDBOX_JWT_PRIVATE_KEY", "LLM_GATEWAY_ANTHROPIC_API_KEY"),
            id="mixed_run_reports_each_missing_variable_once",
        ),
        pytest.param(
            {SuiteKind.ONE_SHOT},
            "codex",
            {"BRAINTRUST_API_KEY": "x", "LLM_GATEWAY_ANTHROPIC_API_KEY": "x"},
            (),
            id="codex_requirement_only_applies_to_sandboxed_runs",
        ),
        pytest.param(
            {SuiteKind.SANDBOXED},
            "codex",
            {"BRAINTRUST_API_KEY": "x", "LLM_GATEWAY_ANTHROPIC_API_KEY": "x", "SANDBOX_JWT_PRIVATE_KEY": "x"},
            ("LLM_GATEWAY_OPENAI_API_KEY",),
            id="sandboxed_codex_run_needs_the_openai_key",
        ),
    ],
)
def test_validate_eval_env_by_kind(
    monkeypatch: pytest.MonkeyPatch,
    kinds: set[SuiteKind],
    agent_runtime: str,
    env: dict[str, str],
    expect_missing: tuple[str, ...],
) -> None:
    for name in ALL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    if not expect_missing:
        validate_eval_env(agent_runtime, kinds=kinds)
        return

    with pytest.raises(PreflightError) as exc_info:
        validate_eval_env(agent_runtime, kinds=kinds)
    message = str(exc_info.value)
    for name in expect_missing:
        assert message.count(name) == 1
    for name in set(ALL_ENV_VARS) - set(expect_missing) - set(env):
        assert name not in message
