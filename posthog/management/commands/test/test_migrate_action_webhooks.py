from inline_snapshot import snapshot
from posthog.cdp.templates.webhook.template_webhook import template as template_webhook
from posthog.management.commands.migrate_action_webhooks import migrate_action_webhooks
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.test.base import BaseTest


advanced_message_format = """Event: [event] [event.event] [event.link] [event.uuid]
Person: [person] [person.link] [person.properties.foo.bar]
Groups: [groups.organization]  [groups.organization.properties.foo.bar]
Action: [action.name] [action.link]"""


class TestMigrateActionWebhooks(BaseTest):
    action: Action

    def setUp(self):
        super().setUp()
        self.team.slack_incoming_webhook = "https://webhooks.slack.com/123"
        self.team.save()
        self.action = Action.objects.create(
            created_by=self.user,
            name="Test Action",
            team_id=self.team.id,
            slack_message_format="[event] triggered by [person]",
            post_to_slack=True,
        )

    def test_dry_run(self):
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=True)
        assert not HogFunction.objects.exists()

    def test_only_specified_team(self):
        migrate_action_webhooks(action_ids=[], team_ids=[9999])
        assert not HogFunction.objects.exists()
        migrate_action_webhooks(action_ids=[], team_ids=[self.team.id])
        assert HogFunction.objects.exists()

    def test_only_specified_actiojns(self):
        migrate_action_webhooks(action_ids=[9999], team_ids=[])
        assert not HogFunction.objects.exists()
        migrate_action_webhooks(action_ids=[self.action.id], team_ids=[])
        assert HogFunction.objects.exists()

    def test_migrates_base_action_config_correctly(self):
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=False)
        self.action.refresh_from_db()

        hog_functons = HogFunction.objects.all()
        assert len(hog_functons) == 1
        hog_function = hog_functons[0]

        assert hog_function.name == f"Webhook for action {self.action.id} (Test Action)"
        assert hog_function.filters == {
            "actions": [{"id": f"{self.action.id}", "name": "Test Action", "type": "actions", "order": 0}],
            "bytecode": ["_h", 29, 3, 1, 4, 1],
        }
        assert hog_function.hog == template_webhook.hog
        assert hog_function.inputs_schema == template_webhook.inputs_schema
        assert hog_function.template_id == template_webhook.id
        assert hog_function.bytecode
        assert hog_function.enabled
        assert hog_function.icon_url == template_webhook.icon_url

        assert self.action.post_to_slack is False

    def test_migrates_message_format(self):
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=False)
        hog_function = HogFunction.objects.all()[0]

        assert hog_function.inputs["url"]["value"] == "https://webhooks.slack.com/123"
        assert hog_function.inputs["method"]["value"] == "POST"
        assert hog_function.inputs["body"]["value"] == snapshot(
            {
                "text": "{event.name} triggered by {person.name}",
                "blocks": [
                    {
                        "text": {
                            "text": "<{event.url}|{event.name}> triggered by <{person.url}|{person.name}>",
                            "type": "mrkdwn",
                        },
                        "type": "section",
                    }
                ],
            }
        )

    def test_migrates_message_format_not_slack(self):
        self.team.slack_incoming_webhook = "https://webhooks.other.com/123"
        self.team.save()
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=False)
        hog_function = HogFunction.objects.all()[0]

        assert hog_function.inputs["url"]["value"] == "https://webhooks.other.com/123"
        assert hog_function.inputs["body"]["value"] == snapshot(
            {"text": "[{event.name}]({event.url}) triggered by [{person.name}]({person.url})"}
        )

    def test_migrates_advanced_message_format(self):
        self.action.slack_message_format = advanced_message_format
        self.action.save()
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=False)
        hog_function = HogFunction.objects.all()[0]

        assert (
            hog_function.inputs["body"]["value"]["text"]
            == """Event: {event.name} {event.event} {event.link} {event.uuid}
Person: {person.name} {person.link} {person.properties.foo.bar}
Groups: {groups.organization.url}  {groups.organization.properties.foo.bar}
Action: Test Action {project.url}/data-management/actions/1""".replace("1", str(self.action.id))
        )

        assert hog_function.inputs["body"]["value"]["blocks"] == [
            {
                "text": {
                    "text": """Event: <{event.url}|{event.name}> {event.event} {event.link} {event.uuid}
Person: <{person.url}|{person.name}> {person.link} {person.properties.foo.bar}
Groups: {groups.organization.url}  {groups.organization.properties.foo.bar}
Action: <{project.url}/data-management/actions/1|Test Action> {project.url}/data-management/actions/1""".replace(
                        "1", str(self.action.id)
                    ),
                    "type": "mrkdwn",
                },
                "type": "section",
            }
        ]

    def test_migrates_advanced_message_format_not_slack(self):
        self.action.slack_message_format = advanced_message_format
        self.action.save()
        self.team.slack_incoming_webhook = "https://webhooks.other.com/123"
        self.team.save()
        migrate_action_webhooks(action_ids=[], team_ids=[], dry_run=False)
        hog_function = HogFunction.objects.all()[0]

        assert hog_function.inputs["body"]["value"] == {
            "text": """\
Event: [{event.name}]({event.url}) {event.event} {event.link} {event.uuid}
Person: [{person.name}]({person.url}) {person.link} {person.properties.foo.bar}
Groups: {groups.organization.url}  {groups.organization.properties.foo.bar}
Action: [Test Action]({project.url}/data-management/actions/1) {project.url}/data-management/actions/1\
""".replace("1", str(self.action.id))
        }
