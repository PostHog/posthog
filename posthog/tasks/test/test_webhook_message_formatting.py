from posthog.models import Action, Event, Person
from posthog.tasks.webhooks import (
    determine_webhook_type,
    get_action_details,
    get_formatted_message,
    get_tokens,
    get_user_details,
    get_value_of_token,
)
from posthog.test.base import BaseTest


class TestWebhookMessage(BaseTest):
    def test_determine_webhook(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        webhook_type = determine_webhook_type(self.team)
        self.assertEqual(webhook_type, "slack")

        self.team.slack_incoming_webhook = "https://outlook.office.com/webhook/"
        webhook_type = determine_webhook_type(self.team)
        self.assertEqual(webhook_type, "teams")

    def test_get_user_details(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        Person.objects.create(
            properties={"email": "test@posthog.com"}, team=self.team, distinct_ids=["2"],
        )
        event1 = Event.objects.create(team=self.team, distinct_id="2")
        user_name, slack_user_markdown = get_user_details(event1, "http://localhost:8000")
        self.assertEqual(
            slack_user_markdown, "<http://localhost:8000/person/2|test@posthog.com>",
        )

        self.team.slack_incoming_webhook = "https://outlook.office.com/webhook/"

        event2 = Event.objects.create(team=self.team, distinct_id="2", properties={"email": "test@posthog.com"})
        user_name, teams_user_markdown = get_user_details(event2, "http://localhost:8000")

        self.assertEqual(
            teams_user_markdown, "[test@posthog.com](http://localhost:8000/person/2)",
        )
        self.assertEqual(user_name, "test@posthog.com")

    def test_get_action_details(self) -> None:
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"email": "test@posthog.com"})
        action1 = Action.objects.create(team=self.team, name="action1", id=1)

        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        action_name, slack_action_markdown = get_action_details(action1, event1, "http://localhost:8000")
        self.assertEqual(
            slack_action_markdown, '"<http://localhost:8000/action/1|action1>"',
        )

        self.team.slack_incoming_webhook = "https://outlook.office.com/webhook/"
        action_name, teams_action_markdown = get_action_details(action1, event1, "http://localhost:8000")
        self.assertEqual(
            teams_action_markdown, '"[action1](http://localhost:8000/action/1)"',
        )

        self.assertEqual(action_name, "action1")

    def test_get_tokens_well_formatted(self) -> None:
        format1 = "[action.name] got did by [user.name]"
        matched_tokens, tokenised_message = get_tokens(format1)
        self.assertEqual(matched_tokens, ["action.name", "user.name"])
        self.assertEqual(tokenised_message, "{} got did by {}")

    def test_get_value_of_token_user_correct(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$browser": "Chrome"})
        action1 = Action.objects.create(team=self.team, name="action1", id=1)

        token_user_name = ["user", "name"]
        text, markdown = get_value_of_token(action1, event1, "http://localhost:8000", token_user_name)
        self.assertEqual(text, "2")
        # markdown output is already tested in test_get_user_details

        token_user_prop = ["user", "browser"]
        text, markdown = get_value_of_token(action1, event1, "http://localhost:8000", token_user_prop)
        self.assertEqual(text, "Chrome")

    def test_get_value_of_token_user_incorrect(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$browser": "Chrome"})
        action1 = Action.objects.create(team=self.team, name="action1", id=1)

        token_user_noprop = ["user", "notaproperty"]
        with self.assertRaises(ValueError):
            text, markdown = get_value_of_token(action1, event1, "http://localhost:8000", token_user_noprop)

    def test_get_formatted_message(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$browser": "Chrome"})
        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            id=1,
            slack_message_format="[user.name] did action from browser [user.browser]",
        )

        text, markdown = get_formatted_message(action1, event1, "https://localhost:8000")
        self.assertEqual(text, "2 did action from browser Chrome")

    def test_get_formatted_message_default(self) -> None:
        """
        If slack_message_format is empty, use the default message format.
        [action] was triggered by [user]
        """
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$browser": "Chrome"})
        action1 = Action.objects.create(team=self.team, name="action1", id=1, slack_message_format="")
        text, markdown = get_formatted_message(action1, event1, "https://localhost:8000")
        self.assertEqual(text, "action1 was triggered by 2")

    def test_get_formatted_message_incorrect(self) -> None:
        self.team.slack_incoming_webhook = "https://hooks.slack.com/services/"
        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$browser": "Chrome"})
        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            id=1,
            slack_message_format="[user.name] did thing from browser [user.bbbrowzer]",
        )
        text, markdown = get_formatted_message(action1, event1, "https://localhost:8000")
        self.assertIn("Error", text)
