from dataclasses import fields
from typing import Any, Union, get_args, get_origin

from posthog.hogql.ast import AST_CLASSES, AST, Expr, Constant


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


def deserialize_hx_ast(hog_ast: dict) -> AST:
    kind = hog_ast.get("__hx_ast", None)
    if kind is None or kind not in AST_CLASSES:
        raise ValueError(f"Invalid or missing '__hx_ast' kind: {kind}")

    cls = AST_CLASSES[kind]
    cls_fields = {f.name: f.type for f in fields(cls)}
    init_args: dict[str, Any] = {}

    for key, value in hog_ast.items():
        if key == "__hx_ast":
            continue
        if key in cls_fields:
            if isinstance(value, dict) and "__hx_ast" in value:
                init_args[key] = deserialize_hx_ast(value)
            elif isinstance(value, list):
                init_args[key] = []
                for item in value:
                    if isinstance(item, dict) and "__hx_ast" in item:
                        init_args[key].append(deserialize_hx_ast(item))
                    elif is_simple_value(item):
                        field_type = unwrap_list(cls_fields[key])
                        if is_ast_subclass(field_type):
                            raise ValueError(
                                f"Invalid type for field '{key}' in AST node '{kind}'. Expected '{field_type.__name__}', got '{type(item).__name__}'"
                            )
                        init_args[key].append(item)
                    else:
                        raise ValueError(f"Unexpected value for field '{key}' in AST node '{kind}'")
            else:
                field_type = unwrap_optional(cls_fields[key])
                # We need an AST node, but we get just a string/number, see if a Constant is expected
                if is_ast_subclass(field_type):
                    if (field_type in (Expr, Constant)) and is_simple_value(value):
                        init_args[key] = Constant(value=value)
                    else:
                        raise ValueError(
                            f"Invalid type for field '{key}' in AST node '{kind}'. Expected {field_type}, got {type(value)}"
                        )
                elif is_simple_value(value):
                    init_args[key] = value
                else:
                    raise ValueError(f"Unexpected value for field '{key}' in AST node '{kind}'")
        else:
            raise ValueError(f"Unexpected field '{key}' for AST node '{kind}'")

    return cls(**init_args)  # type: ignore
