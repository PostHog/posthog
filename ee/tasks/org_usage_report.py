from typing import List

from posthog.tasks.org_usage_report import OrgReport, send_all_reports


def send_all_org_usage_reports(*, dry_run: bool = False) -> List[OrgReport]:
    """
    Creates and sends usage reports for all teams.
    Returns a list of all the successfully sent reports.
    """
    return send_all_reports(dry_run=dry_run)
