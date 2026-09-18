from pathlib import Path

from posthog.tasks.usage_report import BILLABLE_EVENT_EXCLUDED_EVENTS

SKILL_PATH = Path(__file__).parent / "understanding-billing-usage" / "SKILL.md"


def test_event_drilldown_excludes_non_billable_events() -> None:
    skill_content = SKILL_PATH.read_text(encoding="utf-8")

    missing_events = [event for event in BILLABLE_EVENT_EXCLUDED_EVENTS if event not in skill_content]

    assert missing_events == []


def test_product_drilldown_treats_product_data_as_untrusted() -> None:
    skill_content = SKILL_PATH.read_text(encoding="utf-8")

    assert "untrusted evidence" in skill_content


def test_permission_errors_point_to_access_recovery() -> None:
    skill_content = SKILL_PATH.read_text(encoding="utf-8")
    normalized_skill_content = " ".join(skill_content.split())

    assert "If a billing tool returns a permission error, read the error detail" in normalized_skill_content
    assert "Stop only when it says the user does not have billing access" in normalized_skill_content
    assert "does not have billing access for this organization" in normalized_skill_content
    assert "If the permission error points to requested projects or `team_ids`" in normalized_skill_content
