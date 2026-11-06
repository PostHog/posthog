from datetime import UTC, datetime, time, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from lxml import html
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.logic.customer_task_digest import (
    build_customer_task_digest,
    build_customer_task_digest_email,
)
from products.customer_analytics.backend.models import Account, CustomerTask


class TestCustomerTaskDigest(BaseTest):
    @parameterized.expand(
        [
            ("midweek", "2026-09-16T12:00:00+00:00", "America/New_York", 2),
            ("friday", "2026-09-18T12:00:00+00:00", "America/New_York", 0),
            ("saturday", "2026-09-19T12:00:00+00:00", "America/New_York", 0),
            ("spring_dst", "2026-03-08T08:00:00+00:00", "America/New_York", 0),
            ("fall_dst", "2026-11-01T08:00:00+00:00", "America/New_York", 0),
            ("next_local_day", "2026-09-15T23:30:00+00:00", "Asia/Tokyo", 2),
        ]
    )
    def test_sections_follow_project_dates(self, _name: str, now: str, zone: str, upcoming_days: int) -> None:
        self.team.timezone = zone
        reference_time = datetime.fromisoformat(now)
        local_day = reference_time.astimezone(ZoneInfo(zone)).date()
        start = datetime.combine(local_day, time.min, tzinfo=ZoneInfo(zone))
        tomorrow = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=ZoneInfo(zone))
        for name, due in [
            ("before", start - timedelta(seconds=1)),
            ("start", start),
            ("last", tomorrow - timedelta(seconds=1)),
        ]:
            CustomerTask.objects.for_team(self.team.id).create(
                team=self.team, assigned_to=self.user, name=name, due_at=due
            )
        for offset in range(1, 9):
            CustomerTask.objects.for_team(self.team.id).create(
                team=self.team,
                assigned_to=self.user,
                name=f"day-{offset}",
                due_at=tomorrow + timedelta(days=offset - 1),
            )
        digest = build_customer_task_digest(user=self.user, team=self.team, reference_time=reference_time)
        assert digest is not None
        assert [task.name for task in digest.due_today] == ["start", "last"]
        assert [task.name for task in digest.due_this_week] == [
            f"day-{offset}" for offset in range(1, upcoming_days + 1)
        ]
        assert digest.overdue_count == 2

    def test_empty_overdue_only_and_current_task_state(self) -> None:
        now = datetime(2026, 9, 16, 12, tzinfo=UTC)
        assert build_customer_task_digest(user=self.user, team=self.team, reference_time=now) is None
        task = CustomerTask.objects.for_team(self.team.id).create(
            team=self.team, assigned_to=self.user, name="Follow up", due_at=now - timedelta(days=1)
        )
        digest = build_customer_task_digest(user=self.user, team=self.team, reference_time=now)
        assert digest is not None
        assert digest.overdue_count == 1
        assert not digest.due_today and not digest.due_this_week
        assert "due=overdue" in digest.overdue_url
        assert "assignee=me" in digest.overdue_url
        with patch("posthog.email.is_email_available", return_value=True):
            message = build_customer_task_digest_email(digest=digest, user=self.user, campaign_key="test-digest")
        assert "1 overdue task" in message.html_body
        assert "Notification settings" in message.html_body
        for field, value in [
            ("status", "completed"),
            ("status", "canceled"),
            ("archived_at", now),
            ("assigned_to", None),
            ("due_at", None),
        ]:
            setattr(task, field, value)
            task.completed_at = now if task.status == "completed" else None
            task.save()
            assert build_customer_task_digest(user=self.user, team=self.team, reference_time=now) is None
            task.status = "open"
            task.completed_at = None
            task.archived_at = None
            task.assigned_to = self.user
            task.due_at = now - timedelta(days=1)
            task.save()
        task.due_at = now + timedelta(hours=1)
        task.save(update_fields=["due_at"])
        refreshed = build_customer_task_digest(user=self.user, team=self.team, reference_time=now)
        assert refreshed is not None
        assert refreshed.overdue_count == 0
        assert len(refreshed.due_today) == 1
        assert str(task.id) in refreshed.due_today[0].url
        due_today_link = urlsplit(refreshed.due_today_url)
        assert due_today_link.path == f"/project/{self.team.id}/customer_analytics/tasks"
        assert parse_qs(due_today_link.query) == {
            "status": ["open"],
            "assignee": [str(self.user.id)],
            "archive": ["active"],
            "due": ["today"],
        }

    def test_access_filters_lists_and_counts_and_rechecks_membership(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        user = User.objects.create_and_join(self.organization, "digest-reader@example.com", "testpassword")
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Hidden account")
        now = datetime(2026, 9, 16, 12, tzinfo=UTC)
        for due_at in [now - timedelta(days=1), now + timedelta(hours=1)]:
            CustomerTask.objects.for_team(self.team.id).create(
                team=self.team, account=account, assigned_to=user, name="Hidden account task", due_at=due_at
            )
            task = CustomerTask.objects.for_team(self.team.id).create(
                team=self.team, assigned_to=user, name="Hidden task", due_at=due_at
            )
            AccessControl.objects.create(
                team=self.team,
                resource="customer_task",
                resource_id=str(task.id),
                access_level="none",
                organization_member=membership,
            )
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
            organization_member=membership,
        )
        other_team = Team.objects.create(organization=self.organization)
        CustomerTask.objects.for_team(other_team.id).create(
            team=other_team, assigned_to=user, name="Other project", due_at=now
        )
        assert build_customer_task_digest(user=user, team=self.team, reference_time=now) is None
        CustomerTask.objects.for_team(self.team.id).create(team=self.team, assigned_to=user, name="Visible", due_at=now)
        assert build_customer_task_digest(user=user, team=self.team, reference_time=now) is not None
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
            organization_member=membership,
        )
        assert build_customer_task_digest(user=user, team=self.team, reference_time=now) is None


class TestCustomerTaskDigestTemplate(SimpleTestCase):
    @parameterized.expand([(1,), (10,), (11,), (19,)])
    def test_due_today_preview_includes_total_and_remaining_count(self, total: int) -> None:
        tasks = [
            {
                "name": f"Task {index}",
                "url": f"https://example.com/tasks/{index}",
                "due_label": "Today at 09:00 UTC",
            }
            for index in range(1, total + 1)
        ]
        due_today_url = (
            "https://example.com/project/1/customer_analytics/tasks?status=open&assignee=7&archive=active&due=today"
        )
        document = html.fromstring(
            render_to_string(
                "email/customer_task_digest.html",
                {"digest": {"project_name": "Example project", "due_today": tasks, "due_today_url": due_today_url}},
            )
        )

        heading = document.xpath("//h2[starts-with(., 'Due today')]")[0]
        assert heading.text_content() == f"Due today ({total})"
        assert heading.xpath("following-sibling::ul[1]/li/a/text()") == [
            f"Task {index}" for index in range(1, min(total, 10) + 1)
        ]
        if total > 10:
            task_label = "task" if total == 11 else "tasks"
            remaining_link = heading.xpath("following-sibling::p[1]/a")[0]
            assert remaining_link.text_content() == f"+{total - 10} more {task_label} due today"
            assert remaining_link.get("href") == due_today_url
        else:
            assert "more task" not in document.text_content()
