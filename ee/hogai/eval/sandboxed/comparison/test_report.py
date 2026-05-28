"""Unit tests for the comparison report aggregation/rendering (no harness needed)."""

from __future__ import annotations

from ee.hogai.eval.sandboxed.comparison.report import RunResult, render_json, render_markdown, summarize


def _run(arm: str, rep: int, total: int, outcome: bool | None, judge: bool | None, exit_code: int = 0) -> RunResult:
    return RunResult(
        arm=arm,
        task="create_flag",
        rep=rep,
        total_tokens=total,
        input_tokens=int(total * 0.8),
        output_tokens=int(total * 0.2),
        cached_tokens=0,
        duration_seconds=10.0,
        outcome_pass=outcome,
        judge_pass=judge,
        exit_code=exit_code,
    )


def _sample() -> list[RunResult]:
    return [
        _run("cli", 0, 5_000, True, True),
        _run("cli", 1, 7_000, True, False),
        _run("mcp-tools", 0, 120_000, True, True),
        _run("mcp-tools", 1, 130_000, False, True),
        _run("mcp-exec", 0, 9_000, True, True, exit_code=1),
    ]


def test_summarize_means_and_rates():
    s = summarize(_sample())
    assert s["cli"].runs == 2
    assert s["cli"].mean_total_tokens == 6_000
    assert s["cli"].outcome_success_rate == 1.0
    assert s["cli"].judge_success_rate == 0.5
    assert s["mcp-tools"].mean_total_tokens == 125_000
    assert s["mcp-tools"].outcome_success_rate == 0.5
    assert s["mcp-exec"].error_rate == 1.0  # the one mcp-exec run had exit_code 1


def test_summarize_handls_none_rates():
    results = [_run("cli", 0, 5_000, None, None)]
    s = summarize(results)
    assert s["cli"].outcome_success_rate is None
    assert s["cli"].judge_success_rate is None


def test_render_markdown_has_arms_and_relative_column():
    md = render_markdown(_sample())
    assert "CLI vs MCP comparison" in md
    assert "| cli |" in md and "| mcp-tools |" in md and "| mcp-exec |" in md
    # baseline (first arm = cli) is 1.00x; mcp-tools should be ~20x cli
    assert "1.00×" in md
    assert "20.83×" in md  # 125000 / 6000


def test_render_markdown_empty():
    assert "(no results)" in render_markdown([])


def test_render_json_roundtrips():
    import json

    payload = json.loads(render_json(_sample()))
    assert len(payload["runs"]) == 5
    assert set(payload["summary"]) == {"cli", "mcp-tools", "mcp-exec"}
