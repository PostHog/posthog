from parameterized import parameterized

from posthog.temporal.data_modeling.metrics import tier_label


@parameterized.expand(
    [
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:3600-2026-10-21T10:00:00Z", "3600"),
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:2592000:10800-2026-10-21T03:00:00Z", "2592000"),
        ("execute-dag-trino-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:900", "900"),
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b-2026-10-21T10:00:00Z", "ad_hoc"),
        ("materialize-view-manual-run", "ad_hoc"),
        (None, "ad_hoc"),
    ]
)
def test_tier_label(workflow_id: str | None, expected: str) -> None:
    assert tier_label(workflow_id) == expected
