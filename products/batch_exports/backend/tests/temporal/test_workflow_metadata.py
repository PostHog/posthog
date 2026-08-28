import re
import json
from urllib.parse import parse_qs, urlparse

import pytest

from products.batch_exports.backend.temporal.workflow_metadata import (
    STATIC_SUMMARY_MAX_BYTES,
    WorkflowDetails,
    build_logs_link,
    build_static_summary,
    humanize_bytes,
)


def test_build_logs_link_filters_logs_by_workflow_id(settings):
    settings.TEMPORAL_LOGS_PROJECT_ID = 123
    settings.SITE_URL = "https://example.com"

    link = build_logs_link("a-workflow-id")

    assert link is not None
    markdown_match = re.fullmatch(r"\[View logs in PostHog\]\((.+)\)", link)
    assert markdown_match is not None

    url = urlparse(markdown_match.group(1))
    assert url.path == "/project/123/logs"

    params = parse_qs(url.query)
    filter_group = json.loads(params["filterGroup"][0])
    assert filter_group == {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "workflow_id",
                        "value": ["a-workflow-id"],
                        "operator": "exact",
                        "type": "log_attribute",
                    }
                ],
            }
        ],
    }
    # An explicit date range is set so the logs UI shows enough history to find the run.
    assert json.loads(params["dateRange"][0]) == {"date_from": "-1d", "date_to": None}


def test_build_logs_link_disabled_when_no_project_configured(settings):
    settings.TEMPORAL_LOGS_PROJECT_ID = 0
    assert build_logs_link("a-workflow-id") is None


@pytest.mark.parametrize(
    "interval,is_backfill,expected",
    [
        ("hour", False, "Batch export events every hour to S3"),
        ("day", False, "Batch export events every day to S3"),
        ("every 5 minutes", False, "Batch export events every 5 minutes to S3"),
        ("hour", True, "Backfill batch export events every hour to S3"),
    ],
)
def test_build_static_summary(interval, is_backfill, expected):
    assert build_static_summary("S3", "events", interval, is_backfill=is_backfill) == expected


def test_build_static_summary_truncated_to_temporal_byte_limit():
    # A long model name would otherwise push the summary past Temporal's 200-byte cap and be rejected.
    summary = build_static_summary("S3", "events_" * 50, "hour")
    assert len(summary.encode("utf-8")) <= STATIC_SUMMARY_MAX_BYTES
    assert summary.endswith("…")


@pytest.mark.parametrize(
    "num_bytes,expected",
    [
        (0, "0 Bytes"),
        (512, "512 Bytes"),
        (1024, "1.0 KiB"),
        (1572864, "1.5 MiB"),
    ],
)
def test_humanize_bytes(num_bytes, expected):
    assert humanize_bytes(num_bytes) == expected


def test_workflow_details_renders_rows_with_footer_last():
    details = (
        WorkflowDetails(footer="[logs](https://example.com)")
        .add("Team", "1")
        .text("Backfilling `a` → `b`")
        .add("Status", "Completed")
    )
    assert details.render() == "Team: 1\n\nBackfilling `a` → `b`\n\nStatus: Completed\n\n[logs](https://example.com)"


def test_workflow_details_skips_none_values():
    details = WorkflowDetails().add("Records", 0).add("Bytes", None).text(None).add("Status", "Completed")
    # 0 is kept (only None is skipped); None rows and a None footer drop out entirely.
    assert details.render() == "Records: 0\n\nStatus: Completed"


def test_workflow_details_code_block_prevents_markdown_injection():
    # A destination error is user-influenced text; it must render inside a fence, and a fence that
    # the error's own backticks cannot break out of, so a crafted "[link](...)" can't reach the UI.
    error = "boom ``` [View logs](https://attacker.example)"
    rendered = WorkflowDetails().code_block("Error", error).render()

    fence = "````"  # grown past the triple-backtick run in the error
    assert rendered == f"Error:\n{fence}\n{error}\n{fence}"


def test_workflow_details_is_immutable_so_a_base_can_be_reused():
    base = WorkflowDetails().add("Team", "1")

    staged = base.add("Staged records", 5)
    finished = base.add("Status", "Completed")

    # Extending the base does not mutate it, so each render reflects only its own additions.
    assert base.render() == "Team: 1"
    assert staged.render() == "Team: 1\n\nStaged records: 5"
    assert finished.render() == "Team: 1\n\nStatus: Completed"
