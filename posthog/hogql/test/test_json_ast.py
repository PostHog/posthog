import pytest

import orjson

from posthog.hogql import ast
from posthog.hogql.json_ast import deserialize_ast


class TestJsonAstForwardCompat:
    def test_unknown_field_is_dropped_instead_of_crashing(self) -> None:
        # A parser wheel one version ahead of `ast.py` can emit a field the
        # running Python class doesn't declare yet. Forwarding it into the
        # dataclass constructor used to raise `TypeError` and crash startup;
        # the deserializer must drop it and still build the node.
        payload = orjson.dumps({"node": "Field", "chain": ["event"], "field_from_a_future_parser": 42}).decode()

        node = deserialize_ast(payload)

        assert isinstance(node, ast.Field)
        assert node.chain == ["event"]
        assert not hasattr(node, "field_from_a_future_parser")

    def test_known_fields_still_populate(self) -> None:
        payload = orjson.dumps({"node": "Field", "chain": ["event"], "from_asterisk": True}).decode()

        node = deserialize_ast(payload)

        assert isinstance(node, ast.Field)
        assert node.from_asterisk is True

    def test_unknown_node_type_still_raises(self) -> None:
        payload = orjson.dumps({"node": "TotallyNotARealNode"}).decode()

        with pytest.raises(ValueError, match="Unknown AST node type"):
            deserialize_ast(payload)
