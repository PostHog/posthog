from dataclasses import fields
from typing import Any, Union, get_args, get_origin

from posthog.hogql.ast import AST, AST_CLASSES, Constant, Expr, HogQLXAttribute, HogQLXTag


def unwrap_optional(t):
    if get_origin(t) is Union and type(None) in get_args(t):
        # Return the first argument, which is the actual type in Optional[type]
        return next(arg for arg in get_args(t) if arg is not type(None))
    return t


def unwrap_list(t):
    if get_origin(t) is list and len(get_args(t)) == 1:
        return get_args(t)[0]
    return t


def is_ast_subclass(t):
    return isinstance(t, type) and issubclass(t, AST)


def is_simple_value(value: Any) -> bool:
    if isinstance(value, int) or isinstance(value, float) or isinstance(value, str) or isinstance(value, bool):
        return True
    if isinstance(value, list):
        return all(is_simple_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_simple_value(val) for key, val in value.items())
    return False


def deserialize_hx_tag(hog_tag: dict) -> HogQLXTag:
    tag_kind = hog_tag.get("__hx_tag", None)
    if tag_kind is None:
        raise ValueError("Missing '__hx_tag' key in HogQLXTag")

    attributes = []
    for k, v in hog_tag.items():
        if k == "__hx_tag":
            continue
        if isinstance(v, list):
            value = [
                deserialize_hx_ast(item)
                if isinstance(item, dict) and ("__hx_tag" in item or "__hx_ast" in item)
                else item
                for item in v
            ]
        else:
            value = deserialize_hx_ast(v) if isinstance(v, dict) and ("__hx_tag" in v or "__hx_ast" in v) else v
        attributes.append(HogQLXAttribute(name=k, value=value))

    return HogQLXTag(kind=tag_kind, attributes=attributes)


def deserialize_hx_ast(hog_ast: dict) -> AST:
    """
    Deserialize a HX AST and tag dicts into real Python AST classes.
      - Dicts with `__hx_ast` -> AST node
      - Dicts with `__hx_tag` -> HogQLXTag
      - Lists that may contain tags, primitive values, or more lists
    """
    tag_kind = hog_ast.get("__hx_tag")
    if tag_kind is not None:
        return deserialize_hx_tag(hog_ast)

    kind = hog_ast.get("__hx_ast")
    if kind is None or kind not in AST_CLASSES:
        raise ValueError(f"Invalid or missing '__hx_ast' kind: {kind}")

    cls = AST_CLASSES[kind]
    cls_fields = {f.name: f.type for f in fields(cls)}
    init_args: dict[str, Any] = {}

    def _deserialize(value: Any, field_type: type) -> Any:
        if isinstance(value, dict) and "__hx_tag" in value:
            return deserialize_hx_tag(value)

        if isinstance(value, dict) and "__hx_ast" in value:
            return deserialize_hx_ast(value)

        if isinstance(value, list):
            elem_type = unwrap_list(field_type)
            return [_deserialize(v, elem_type) for v in value]

        if is_ast_subclass(field_type):
            if (field_type in (Expr, Constant)) and is_simple_value(value):
                return Constant(value=value)
            raise ValueError(
                f"Invalid type for field expecting '{field_type.__name__}', " f"got '{type(value).__name__}'"
            )

        if is_simple_value(value):
            return value

        raise ValueError(f"Unexpected value of type '{type(value).__name__}' for field " f"expecting '{field_type}'")

    for key, value in hog_ast.items():
        if key == "__hx_ast":
            continue
        if key not in cls_fields:
            raise ValueError(f"Unexpected field '{key}' for AST node '{kind}'")

        init_args[key] = _deserialize(value, cls_fields[key])

    return cls(**init_args)  # type: ignore
