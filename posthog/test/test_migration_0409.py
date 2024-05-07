from posthog.test.base import NonAtomicTestMigrations

from posthog.models.action import Action
from posthog.models.action.action_step import ActionStep
from posthog.models.team import Team
from posthog.models.organization import Organization


class TestActionStepsJSONMigration(NonAtomicTestMigrations):
    migrate_from = "0408_team_modifiers"
    migrate_to = "0409_action_steps_json_alter_actionstep_action"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps):
        org = Organization.objects.create(name="o1")
        team = Team.objects.create(name="t1", organization=org)

        # We create this with sql as it won't have the new fields
        sql = f"""INSERT INTO posthog_action (name, team_id, description, created_at, updated_at, deleted, post_to_slack, slack_message_format, is_calculating, last_calculated_at)
                VALUES ('action1', {team.pk}, '', '2022-01-01', '2022-01-01', FALSE, FALSE, '', FALSE, '2022-01-01') RETURNING id;
                """

        action = Action.objects.raw(sql)[0]

        # We create this with sql as it won't have the new fields
        sql = f"""INSERT INTO posthog_actionstep (action_id, tag_name, text, text_matching, href, href_matching, selector, url, url_matching, event, properties)
                VALUES ({action.pk}, 'tag1', 'text1', 'exact', 'href1', 'exact', 'selector1', 'url1', 'exact', 'event1', '{{"key1": "value1"}}') RETURNING id;
                """

        ActionStep.objects.raw(sql)[0]

    def test_migrate_action_steps(self):
        apps = self.apps
        if apps is None:
            # obey mypy
            raise Exception("apps is None")

        all_actions = Action.objects.all()

        assert len(all_actions) == 1

        assert all_actions[0].steps_json == [
            {
                "tag_name": "tag1",
                "text": "text1",
                "text_matching": "exact",
                "href": "href1",
                "href_matching": "exact",
                "selector": "selector1",
                "url": "url1",
                "url_matching": "exact",
                "event": "event1",
                "properties": {"key1": "value1"},
            }
        ]
