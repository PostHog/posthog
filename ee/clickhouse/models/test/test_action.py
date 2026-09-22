from posthog.test.base import BaseTest

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import action_to_expr

from products.actions.backend.models.action import Action

from common.hogvm.python.operation import (
    HOGQL_BYTECODE_IDENTIFIER as _H,
    HOGQL_BYTECODE_VERSION,
    Operation as op,
)


class TestActionBytecode(BaseTest):
    def test_bytecode_for_hogql_step_property(self):
        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [{"key": "toInt(properties.filters_count) > 10", "type": "hogql"}],
                }
            ],
        )

        self.assertEqual(action1.bytecode, create_bytecode(action_to_expr(action1)).bytecode)
        self.assertEqual(
            action1.bytecode,
            [
                _H,
                HOGQL_BYTECODE_VERSION,
                # event = 'insight viewed'
                op.STRING,
                "insight viewed",
                op.STRING,
                "event",
                op.GET_GLOBAL,
                1,
                op.EQ,
                # toInt(properties.filters_count) > 10
                op.INTEGER,
                10,
                op.STRING,
                "filters_count",
                op.STRING,
                "properties",
                op.GET_GLOBAL,
                2,
                op.CALL_GLOBAL,
                "toInt",
                1,
                op.GT,
                # and
                op.AND,
                2,
            ],
        )
