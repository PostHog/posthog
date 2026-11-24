import os
from pathlib import Path

from posthog.data_access_policy import allowed_view_actions

BASELINE = Path(__file__).with_name("metadata_only_allowed_routes_baseline.txt")


def test_metadata_only_allowed_routes_match_the_reviewed_baseline() -> None:
    current = allowed_view_actions()
    if os.environ.get("UPDATE_METADATA_ONLY_BASELINE") == "1":
        BASELINE.write_text("\n".join(current) + "\n")
    reviewed = [line for line in BASELINE.read_text().splitlines() if line]
    added = sorted(set(current) - set(reviewed))
    removed = sorted(set(reviewed) - set(current))
    assert not added and not removed, (
        "Metadata-only tokens can now reach a different set of view actions. "
        "Check that each added action returns no project data, or block it in posthog/data_access_policy.py. "
        "Then update the baseline with UPDATE_METADATA_ONLY_BASELINE=1 and this test.\n"
        f"Added: {added}\nRemoved: {removed}"
    )
