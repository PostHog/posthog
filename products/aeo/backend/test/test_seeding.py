from pathlib import Path
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from posthog.models.team import Team

from products.aeo.backend.engines import MAX_PROMPT_LENGTH
from products.aeo.backend.seeding import collect_candidates

# Only the id is read by the code under test, so a stub keeps these cases off the database.
TEAM = cast(Team, SimpleNamespace(id=1))


def _csv(tmp_path: Path) -> str:
    path = tmp_path / "control.csv"
    path.write_text("prompt\nWhat is the best web analytics tool?\nBest open source session replay?\n")
    return str(path)


def test_failing_analytics_source_does_not_abort_csv_import(tmp_path: Path) -> None:
    with patch("products.aeo.backend.seeding.execute_hogql_query", side_effect=RuntimeError("clickhouse down")):
        candidates, notes = collect_candidates(TEAM, source="all", csv_path=_csv(tmp_path), expand=False)

    texts = [c.text for c in candidates]
    assert "What is the best web analytics tool?" in texts
    assert "Best open source session replay?" in texts
    assert any("unavailable, skipped" in note for note in notes)


def test_failing_expansion_does_not_abort_csv_import(tmp_path: Path) -> None:
    with (
        patch(
            "products.aeo.backend.seeding.fetch_ai_entry_paths",
            return_value=[{"path": "/pricing", "sessions": 5}],
        ),
        patch(
            "products.aeo.backend.seeding.resolve_ai_gateway_config",
            return_value=SimpleNamespace(url="https://gw.test/v1", api_key="k"),
        ),
        patch("products.aeo.backend.seeding.gateway_post_json", side_effect=RuntimeError("gateway 500")),
    ):
        candidates, notes = collect_candidates(TEAM, source="ai_entry_pages", csv_path=_csv(tmp_path), expand=True)

    assert "What is the best web analytics tool?" in [c.text for c in candidates]
    assert any("ai_entry_pages_expand source unavailable, skipped" in note for note in notes)


def test_oversized_candidate_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "oversized.csv"
    path.write_text(f"prompt\nWhat is the best web analytics tool?\n{'a' * (MAX_PROMPT_LENGTH + 1)}\n")

    with patch("products.aeo.backend.seeding.execute_hogql_query", side_effect=RuntimeError("clickhouse down")):
        candidates, notes = collect_candidates(TEAM, source="all", csv_path=str(path), expand=False)

    assert [c.text for c in candidates] == ["What is the best web analytics tool?"]
    assert any(f"over {MAX_PROMPT_LENGTH} characters" in note for note in notes)
