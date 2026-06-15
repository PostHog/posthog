import copy

from posthog.hogql import ast
from posthog.hogql.base import AST


def test_deepcopy_is_independent_of_original():
    node = ast.Field(chain=["a", "b"])
    clone = copy.deepcopy(node)
    clone.chain.append("c")
    assert node.chain == ["a", "b"]
    assert clone is not node
    assert clone.chain is not node.chain


def test_deepcopy_preserves_shared_subtrees():
    shared = ast.Constant(value=1)
    node = ast.Tuple(exprs=[shared, shared])
    clone = copy.deepcopy(node)
    assert clone.exprs[0] is clone.exprs[1]
    assert clone.exprs[0] is not shared


def test_deepcopy_preserves_resolved_type_cycle():
    select_type = ast.SelectQueryType(aliases={}, columns={}, tables={}, anonymous_tables=[])
    field_type = ast.FieldType(name="x", table_type=select_type)
    select_type.columns = {"x": field_type}
    node = ast.Field(chain=["x"], type=field_type)

    clone = copy.deepcopy(node)

    assert clone.type is not field_type
    assert clone.type.table_type.columns["x"] is clone.type


def test_deepcopy_handles_self_referential_container_value():
    value: list = [1]
    value.append(value)

    clone = copy.deepcopy(ast.Constant(value=value))

    assert clone.value is not value
    assert clone.value[1] is clone.value


def test_deepcopy_deep_copies_dict_fields():
    node = ast.SelectQueryType(aliases={}, columns={"a": ast.IntegerType()}, tables={}, anonymous_tables=[])
    clone = copy.deepcopy(node)
    assert clone.columns is not node.columns
    assert clone.columns["a"] is not node.columns["a"]
    assert isinstance(clone.columns["a"], ast.IntegerType)


def test_deepcopy_clears_nothing_and_matches_structure():
    node = ast.And(
        exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=["a"]), right=ast.Constant(value=1), op=ast.CompareOperationOp.Eq
            ),
            ast.Constant(value=True),
        ]
    )
    clone = copy.deepcopy(node)
    assert isinstance(clone, ast.And)
    assert clone is not node
    assert clone.exprs[0] is not node.exprs[0]
    assert clone.exprs[0].op == ast.CompareOperationOp.Eq
    assert clone.exprs[1].value is True


def test_deepcopy_returns_ast_subclass_instance():
    assert isinstance(copy.deepcopy(ast.Constant(value=1)), ast.Constant)
    assert isinstance(copy.deepcopy(ast.Field(chain=["x"])), AST)
