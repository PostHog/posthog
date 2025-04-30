import typing

from mypy.nodes import ARG_POS, Argument, Var
from mypy.plugin import ClassDefContext, Plugin
from mypy.plugins.common import add_method_to_class
from mypy.plugins.dataclasses import dataclass_class_maker_callback
from mypy.types import AnyType, TypeOfAny, UnboundType


def transform(ctx: ClassDefContext) -> None:
    """Dataclass handling and adding special methods."""
    dataclass_class_maker_callback(ctx)

    self_type = ctx.api.named_type(ctx.cls.fullname)
    any_type = AnyType(TypeOfAny.special_form)

    str_type = ctx.api.named_type_or_none("builtins.str")
    if str_type is None:
        str_type = UnboundType("builtins.str")  # type: ignore

    dict_type = ctx.api.named_type("builtins.dict", [str_type, any_type])  # type: ignore
    dict_arg = Argument(variable=Var("d"), type_annotation=dict_type, initializer=None, kind=ARG_POS)

    add_method_to_class(
        ctx.api,
        ctx.cls,
        "from_dict",
        args=[dict_arg],
        return_type=self_type,
        is_classmethod=True,
    )


class ConfigMypyPlugin(Plugin):
    """Mypy plugin to treat our config classes like dataclasses."""

    def get_class_decorator_hook(self, fullname: str) -> typing.Callable[[ClassDefContext], None] | None:
        if fullname == "posthog.temporal.data_imports.pipelines.source.config.config":
            return transform
        return None


def plugin(version: str):
    return ConfigMypyPlugin
