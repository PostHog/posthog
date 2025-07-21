from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from posthog.models import Team
from posthog.test.base import NonAtomicBaseTest


class TestSQLMixins(NonAtomicBaseTest):
    @property
    def _node(self):
        class DummyNode(HogQLGeneratorMixin):
            def __init__(self, team: Team):
                self._team = team

        return DummyNode(self.team)

    async def test_construct_system_prompt(self):
        mixin = self._node
        prompt_template = await mixin._construct_system_prompt()
        prompt = prompt_template.format()
        self.assertIn("<project_schema>", prompt)
        self.assertIn("Table", prompt)
        self.assertIn("<core_memory>", prompt)

    async def test_assert_database_is_cached(self):
        mixin = self._node
        database = await mixin._get_database()
        self.assertEqual(mixin._database_instance, database)
