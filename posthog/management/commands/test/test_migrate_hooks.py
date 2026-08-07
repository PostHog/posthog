from posthog.test.base import BaseTest

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.test.template_fixtures import zapier_template
from posthog.management.commands.migrate_hooks import migrate_hooks

from products.actions.backend.models.action import Action
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hook import Hook

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


class TestMigrateHooks(BaseTest):
    action: Action
    hook: Hook

    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(
            created_by=self.user,
            name="Test Action",
            team_id=self.team.id,
            slack_message_format="[event] triggered by [person]",
            post_to_slack=True,
        )

        self.hook = Hook.objects.create(
            team=self.team,
            target="https://hooks.zapier.com/abcd/",
            event="action_performed",
            resource_id=self.action.id,
            user_id=self.user.id,
        )

        # The Zapier template lives in the Node service, which these tests do not run,
        # so seed the row resolved by template_id.
        self.zapier_template = sync_template_to_db(zapier_template)

    def test_dry_run(self):
        migrate_hooks(hook_ids=[], team_ids=[], dry_run=True)
        assert not HogFunction.objects.exists()

    def test_only_specified_team(self):
        migrate_hooks(hook_ids=[], team_ids=[9999])
        assert not HogFunction.objects.exists()
        migrate_hooks(hook_ids=[], team_ids=[self.team.id])
        assert HogFunction.objects.exists()

    def test_only_specified_hooks(self):
        migrate_hooks(hook_ids=["9999"], team_ids=[])
        assert not HogFunction.objects.exists()
        migrate_hooks(hook_ids=[self.hook.id], team_ids=[])
        assert HogFunction.objects.exists()

    def test_migrates_hook_correctly(self):
        migrate_hooks(hook_ids=[], team_ids=[], dry_run=False)

        hog_functions = HogFunction.objects.all()
        assert len(hog_functions) == 1
        hog_function = hog_functions[0]

        assert hog_function.name == f"Zapier webhook for action {self.action.id}"
        assert hog_function.filters == {
            "source": "events",
            "actions": [{"id": f"{self.action.id}", "name": "", "type": "actions", "order": 0}],
            "bytecode": ["_H", HOGQL_BYTECODE_VERSION, 29],
        }
        assert hog_function.hog == self.zapier_template.code
        assert (
            hog_function.description == f"{self.zapier_template.description} Migrated from legacy hook {self.hook.id}."
        )
        assert hog_function.inputs_schema == self.zapier_template.inputs_schema
        assert hog_function.template_id == self.zapier_template.template_id
        assert hog_function.bytecode
        assert hog_function.enabled
        assert hog_function.icon_url == self.zapier_template.icon_url

        assert Hook.objects.count() == 0
