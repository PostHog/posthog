from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import FunctionType

import pytest
from unittest.mock import patch

from posthog.models.scoping import peer_lazy_loads

BASELINED = "posthog.Thing.team posthog/api/thing.py:ThingSerializer.get_team"
NEW = "posthog.Thing.owner posthog/api/thing.py:ThingSerializer.get_owner"


def _observe(directory: Path, observations: list[tuple[str, str]]) -> None:
    with patch.dict("os.environ", {peer_lazy_loads.DIR_ENV: str(directory)}):
        observer = peer_lazy_loads.Observer()
        for status, entry in observations:
            observer.observe(status, entry)


@pytest.mark.parametrize(
    "mode,entry,blocked,status",
    [
        ("", BASELINED, None, "baselined"),
        ("", NEW, NEW, "blocked"),
        ("record", NEW, None, "blocked"),
    ],
    ids=["baselined_site_batches", "new_site_blocks", "record_mode_allows_new_site"],
)
def test_blocked_entry(mode: str, entry: str, blocked: str | None, status: str) -> None:
    model_field, site = entry.split(" ")
    model, field = model_field.rsplit(".", 1)
    with (
        patch.object(peer_lazy_loads, "baseline", return_value=frozenset({BASELINED})),
        patch.object(peer_lazy_loads, "call_site", return_value=site),
        patch.object(peer_lazy_loads.OBSERVER, "observe") as observe,
        patch.dict("os.environ", {peer_lazy_loads.MODE_ENV: mode}),
    ):
        assert peer_lazy_loads.blocked_entry(model, field) == blocked

    observe.assert_called_once_with(status, entry)


def _call(function: Callable[[], str]) -> str:
    return function()


def _relocated(path: str, qualname: str) -> Callable[[Callable[[], str]], str]:
    code = _call.__code__.replace(co_filename=path, co_qualname=qualname)
    return FunctionType(code, _call.__globals__)


def test_call_site_skips_this_module_and_names_app_code_under_unnormalized_paths() -> None:
    detour = f"{peer_lazy_loads.REPO_ROOT}/products/thing/../.."
    blocked_entry = _relocated(f"{detour}/posthog/models/scoping/peer_lazy_loads.py", "blocked_entry")
    get_owner = _relocated(f"{detour}/posthog/api/thing.py", "get_owner")

    assert get_owner(partial(blocked_entry, peer_lazy_loads.call_site)) == "posthog/api/thing.py:get_owner"


def test_write_baseline_merges_observations_sorted_and_unique(tmp_path: Path) -> None:
    _observe(tmp_path / "shard-1", [("blocked", NEW), ("baselined", BASELINED)])
    _observe(tmp_path / "shard-2", [("blocked", NEW)])
    baseline_path = tmp_path / "baseline.txt"

    peer_lazy_loads.write_baseline(tmp_path, baseline_path)

    lines = baseline_path.read_text().splitlines()
    assert lines[0].startswith("#")
    assert [line for line in lines if not line.startswith("#")] == [NEW, BASELINED]


@pytest.mark.parametrize(
    "observations,full_run,mode,expected",
    [
        ([("baselined", BASELINED)], True, "", []),
        ([], True, "", [f"Baseline entry no longer happens: {BASELINED}"]),
        ([], False, "", []),
        ([("baselined", BASELINED), ("blocked", NEW)], False, "", [f"Lazy load is not in the baseline: {NEW}"]),
        ([("baselined", BASELINED), ("blocked", NEW)], True, "record", []),
    ],
    ids=["clean", "stale_on_full_run", "stale_ignored_on_narrowed_run", "blocked_site", "record_mode"],
)
def test_check(
    tmp_path: Path, observations: list[tuple[str, str]], full_run: bool, mode: str, expected: list[str]
) -> None:
    _observe(tmp_path / "shard-1", observations)
    baseline_path = tmp_path / "baseline.txt"
    baseline_path.write_text(f"# header\n{BASELINED}\n")

    with patch.dict("os.environ", {peer_lazy_loads.MODE_ENV: mode}):
        assert peer_lazy_loads.check(tmp_path, baseline_path, full_run=full_run) == expected
