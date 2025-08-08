from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from posthog.test.base import NonAtomicBaseTest


class TestSQLMixins(NonAtomicBaseTest):
    @property
    def _node(self):
        class DummyNode(HogQLGeneratorMixin):
            def __init__(self, team, user):
                self.__team = team
                self.__user = user

            @property
            def _team(self):
                return self.__team

            @property
            def _user(self):
                return self.__user

        return DummyNode(self.team, self.user)

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

    async def test_parses_queries_with_placeholders(self):
        mixin = self._node
        query = "SELECT properties FROM events WHERE {filters} AND {custom_filter}"
        database = await mixin._get_database()
        result = await mixin._parse_generated_hogql(query, mixin._get_default_hogql_context(database))
        self.assertEqual(result, query)
