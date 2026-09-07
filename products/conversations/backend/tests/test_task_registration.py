from django.test import SimpleTestCase

from posthog.celery import app

# Celery keys tasks by this string, not by import path. A later split of tasks.py
# that drops a pin would leave queued messages and Beat entries unresolved.
EXPECTED_TASK_NAMES = {
    "products.conversations.backend.tasks.process_supporthog_event",
    "products.conversations.backend.tasks.process_supporthog_interactivity",
    "products.conversations.backend.tasks.post_reply_to_slack",
    "products.conversations.backend.tasks.send_email_reply",
    "products.conversations.backend.tasks.flush_pending_email_replies",
    "products.conversations.backend.tasks.send_teams_help",
    "products.conversations.backend.tasks.process_teams_event",
    "products.conversations.backend.tasks.post_reply_to_teams",
    "products.conversations.backend.tasks.post_reply_to_teams_via_graph",
    "products.conversations.backend.tasks.poll_team_shared_channels",
    "products.conversations.backend.tasks.poll_teams_shared_channels",
    "products.conversations.backend.tasks.wake_snoozed_tickets",
    "products.conversations.backend.tasks.process_github_event",
    "products.conversations.backend.tasks.post_reply_to_github",
    "products.conversations.backend.tasks.create_github_issue",
}


class TestConversationsTaskRegistration(SimpleTestCase):
    def test_expected_task_names_resolve(self) -> None:
        app.loader.import_default_modules()
        registered = {name for name in app.tasks if name.startswith("products.conversations.backend.tasks.")}
        assert registered == EXPECTED_TASK_NAMES
