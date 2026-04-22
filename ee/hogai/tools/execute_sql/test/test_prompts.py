from django.test import SimpleTestCase

from ee.hogai.tools.execute_sql.prompts import EXECUTE_SQL_SYSTEM_PROMPT


class TestExecuteSQLPrompts(SimpleTestCase):
    def test_system_prompt_teaches_sql_variable_discovery(self):
        self.assertIn("system.insight_variables", EXECUTE_SQL_SYSTEM_PROMPT)
        self.assertIn("FROM system.insight_variables", EXECUTE_SQL_SYSTEM_PROMPT)
        self.assertIn("There is no list/get tool", EXECUTE_SQL_SYSTEM_PROMPT)
