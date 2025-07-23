from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from posthog.hogql import ast

## ::NB:: Sync this list with frontend/src/queries/nodes/HogQLX/render.tsx
## Sanitization is done on the client side, as we can never be sure what tuple('__hx_tag', 'tag_name') comes our way.
HOGQLX_COMPONENTS = ["Sparkline", "RecordingButton", "ExplainCSPReport"]
HOGQLX_TAGS_SPECIAL = [
    "a",
    "blink",
    "marquee",
    "redacted",
]
HOGQLX_TAGS_NO_ATTRIBUTES = [
    "em",
    "strong",
    "span",
    "div",
    "p",
    "pre",
    "code",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "hr",
    "b",
    "i",
    "u",
]
HOGQLX_TAGS = HOGQLX_TAGS_SPECIAL + HOGQLX_TAGS_NO_ATTRIBUTES


def convert_tag_to_hx(node: ast.HogQLXTag) -> ast.Tuple:
    attrs: list[ast.Expr] = [
        ast.Constant(value="__hx_tag"),
        ast.Constant(value=node.kind),
    ]
    for attribute in node.attributes:
        attrs.append(convert_to_hx(attribute.name))
        attrs.append(convert_to_hx(attribute.value))
    return ast.Tuple(exprs=attrs)


def convert_dict_to_hx(node: ast.Dict) -> ast.Tuple:
    attrs: list[ast.Expr] = [ast.Constant(value="__hx_tag"), ast.Constant(value="__hx_obj")]
    for attribute in node.items:
        attrs.append(convert_to_hx(attribute[0]))
        attrs.append(convert_to_hx(attribute[1]))
    return ast.Tuple(exprs=attrs)


def convert_dataclass_to_hx(node: BaseModel) -> ast.Tuple:
    attrs: list[ast.Expr] = [
        ast.Constant(value="__hx_tag"),
        ast.Constant(value=node.__class__.__name__),
    ]
    for field_name, field_value in node.model_dump(exclude_none=True).items():
        if field_value is not None:
            attrs.append(ast.Constant(value=field_name))
            attrs.append(convert_to_hx(field_value))
    return ast.Tuple(exprs=attrs)


def convert_to_hx(node: Any) -> ast.Expr:
    if isinstance(node, ast.HogQLXTag):
        return convert_tag_to_hx(node)
    if isinstance(node, ast.Dict):
        return convert_dict_to_hx(node)
    if isinstance(node, ast.Array) or isinstance(node, ast.Tuple):
        return ast.Tuple(exprs=[convert_to_hx(x) for x in node.exprs])
    if isinstance(node, ast.Expr):
        return node
    if isinstance(node, list) or isinstance(node, tuple):
        return ast.Tuple(exprs=[convert_to_hx(x) for x in node])
    if isinstance(node, dict):
        resp = ast.Tuple(exprs=[ast.Constant(value="__hx_tag"), ast.Constant(value="__hx_obj")])
        for key, value in node.items():
            if value is not None:
                resp.exprs.append(ast.Constant(value=key))
                resp.exprs.append(convert_to_hx(value))
        return resp
    if isinstance(node, StrEnum):
        return ast.Constant(value=str(node))
    if isinstance(node, BaseModel):
        return convert_dataclass_to_hx(node)
    if (
        node is None
        or isinstance(node, str)
        or isinstance(node, int)
        or isinstance(node, float)
        or isinstance(node, bool)
    ):
        return ast.Constant(value=node)
    return ast.Constant(value=node)
