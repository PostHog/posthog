"""Which visitor handles each resource kind.

Core declares the visitors it holds in `CORE_VISITORS` in `visitors/__init__.py`. A product declares
the visitors for its models in `RESOURCE_TRANSFER_VISITORS` in `backend/resource_transfer/`, and the
registry imports that module through `load_product_modules`, so the transfer framework names no product.

The registry builds on first use. Eager building would put every product's visitor module on the
`django.setup()` import path, which `posthog/test/repo_invariants/test_startup_import_budget.py` keeps clear.
"""

from collections.abc import Iterable, Mapping
from functools import cache
from typing import get_args

from django.db import models

from posthog.dataclasses import frozen
from posthog.models.resource_transfer.types import ResourceKind
from posthog.models.resource_transfer.visitors import CORE_VISITORS, ResourceTransferVisitor
from posthog.products import load_product_modules

PRODUCT_VISITOR_MODULE = "resource_transfer"
PRODUCT_VISITOR_ATTRIBUTE = "RESOURCE_TRANSFER_VISITORS"
CORE_VISITOR_MODULE = "posthog.models.resource_transfer.visitors"

RESOURCE_KINDS: frozenset[str] = frozenset(get_args(ResourceKind))


class ResourceTransferRegistryError(Exception):
    pass


@frozen
class VisitorRegistry:
    by_kind: Mapping[str, type[ResourceTransferVisitor]]
    by_model: Mapping[type[models.Model], type[ResourceTransferVisitor]]


def build_registry(declarations: Iterable[tuple[str, object]]) -> VisitorRegistry:
    """Index `(declaring module, visitor)` pairs by kind and by model.

    Raises when an entry is not a visitor, when a kind or a model has two visitors, or when a
    `ResourceKind` has none. A kind without a visitor would otherwise drop out of transfers and out
    of the field snapshot tests without a failure, for example when a product renames its
    `backend/resource_transfer/` package or leaves a visitor out of its tuple.
    """
    by_kind: dict[str, type[ResourceTransferVisitor]] = {}
    by_model: dict[type[models.Model], type[ResourceTransferVisitor]] = {}
    declared_by: dict[str, str] = {}
    for module, visitor in declarations:
        if (
            not (isinstance(visitor, type) and issubclass(visitor, ResourceTransferVisitor))
            or visitor is ResourceTransferVisitor
        ):
            raise ResourceTransferRegistryError(
                f"{module} declares {visitor!r}, which is not a ResourceTransferVisitor subclass"
            )
        if visitor.kind not in RESOURCE_KINDS:
            raise ResourceTransferRegistryError(
                f"{module} declares {visitor.__name__} for {visitor.kind!r}, which is not a ResourceKind"
            )
        if visitor.kind in by_kind:
            raise ResourceTransferRegistryError(
                f"{module} and {declared_by[visitor.kind]} both declare a visitor for {visitor.kind!r}"
            )
        model = visitor.get_model()
        if model in by_model:
            raise ResourceTransferRegistryError(
                f"{visitor.__name__} and {by_model[model].__name__} both handle {model.__name__}"
            )
        by_kind[visitor.kind] = visitor
        by_model[model] = visitor
        declared_by[visitor.kind] = module

    missing = sorted(RESOURCE_KINDS - by_kind.keys())
    if missing:
        raise ResourceTransferRegistryError(f"No visitor is declared for {', '.join(missing)}")
    return VisitorRegistry(by_kind=by_kind, by_model=by_model)


@cache
def get_registry() -> VisitorRegistry:
    declarations: list[tuple[str, object]] = [(CORE_VISITOR_MODULE, visitor) for visitor in CORE_VISITORS]
    for module in load_product_modules(PRODUCT_VISITOR_MODULE):
        declared = getattr(module, PRODUCT_VISITOR_ATTRIBUTE, None)
        if not isinstance(declared, tuple):
            raise ResourceTransferRegistryError(
                f"{module.__name__}.{PRODUCT_VISITOR_ATTRIBUTE} must be a tuple of ResourceTransferVisitor subclasses"
            )
        declarations.extend((module.__name__, visitor) for visitor in declared)
    return build_registry(declarations)
