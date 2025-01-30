from dataclasses import fields
from typing import Any, Union, get_args, get_origin

from posthog.hogql.ast import AST_CLASSES, AST, Constant


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


def deserialize_hog_ast(hog_ast: dict) -> AST:
    kind = hog_ast.pop("__hqx", None)
    if kind is None or kind not in AST_CLASSES:
        raise ValueError(f"Invalid or missing '__hqx' kind: {kind}")

    cls = AST_CLASSES[kind]
    cls_fields = {f.name: f.type for f in fields(cls)}
    init_args: dict[str, Any] = {}

    for key, value in hog_ast.items():
        if key in cls_fields:
            if isinstance(value, dict) and "__hqx" in value:
                init_args[key] = deserialize_hog_ast(value)
            elif isinstance(value, list):
                field_type = unwrap_list(cls_fields[key])
                init_args[key] = []
                for item in value:
                    if isinstance(item, dict) and "__hqx" in item:
                        init_args[key].append(deserialize_hog_ast(item))
                    elif is_ast_subclass(field_type):
                        init_args[key].append(Constant(value=item))
                    else:
                        init_args[key].append(item)
            else:
                field_type = unwrap_optional(cls_fields[key])
                if is_ast_subclass(field_type):
                    init_args[key] = Constant(value=value)
                else:
                    init_args[key] = value
        else:
            raise ValueError(f"Unexpected field '{key}' for AST node '{kind}'")

    return cls(**init_args)  # type: ignore
