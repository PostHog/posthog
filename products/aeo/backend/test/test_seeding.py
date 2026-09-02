from pathlib import Path
from types import SimpleNamespace

from unittest.mock import patch

from products.aeo.backend.seeding import collect_candidates

TEAM = SimpleNamespace(id=1)


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
