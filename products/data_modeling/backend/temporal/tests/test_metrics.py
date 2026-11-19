from parameterized import parameterized

from products.data_modeling.backend.temporal.metrics import error_code, tier_label


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


@parameterized.expand(
    [
        (
            "[TRINO_TABLE_LOCATOR_MISSING] table invoices is not supported by the Trino backend.",
            "TRINO_TABLE_LOCATOR_MISSING",
        ),
        (
            'TrinoUserError(type=USER_ERROR, name=TYPE_MISMATCH, message="line 1:7: Cannot apply operator: date - integer", query_id=q1)',
            "TYPE_MISMATCH",
        ),
        ("Trino model execution exceeded its 360-minute deadline after 2 attempts", "DEADLINE_EXCEEDED"),
        ("Trino model execution was canceled or exceeded its deadline", "DEADLINE_EXCEEDED"),
        ("error 503: service unavailable", "HTTP_503"),
        ("Cannot redefine an alias with the name: TrinoUserError(type=USER_ERROR, name=TYPE_MISMATCH,", "other"),
    ]
)
def test_error_code(error: str, expected: str) -> None:
    assert error_code(error) == expected
