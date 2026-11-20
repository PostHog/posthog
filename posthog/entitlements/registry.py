from collections.abc import Iterable, Iterator, Sequence
from functools import lru_cache

from posthog.dataclasses import frozen
from posthog.entitlements.contracts import EntitlementReactor
from posthog.products import load_product_modules

CORE_ENTITLEMENT_REACTORS: tuple[EntitlementReactor, ...] = ()


@frozen
class EntitlementReactorRegistry:
    reactors: tuple[EntitlementReactor, ...]

    def __post_init__(self) -> None:
        reactors = tuple(self.reactors)
        seen: set[str] = set()
        for reactor in reactors:
            if reactor.key in seen:
                raise ValueError(f"Duplicate entitlement reactor key: {reactor.key}")
            seen.add(reactor.key)
        object.__setattr__(self, "reactors", reactors)

    def __iter__(self) -> Iterator[EntitlementReactor]:
        return iter(self.reactors)

    def selected(self, keys: Iterable[str]) -> tuple[EntitlementReactor, ...]:
        selected = frozenset(keys)
        unknown = selected - {reactor.key for reactor in self.reactors}
        if unknown:
            raise ValueError(f"Unknown entitlement reactor keys: {', '.join(sorted(unknown))}")
        return tuple(reactor for reactor in self.reactors if reactor.key in selected)


@lru_cache(maxsize=1)
def get_entitlement_reactor_registry() -> EntitlementReactorRegistry:
    reactors = list(CORE_ENTITLEMENT_REACTORS)
    for module in load_product_modules("entitlement_reactors"):
        declared: Sequence[EntitlementReactor] = getattr(module, "ENTITLEMENT_REACTORS", ())
        reactors.extend(declared)
    return EntitlementReactorRegistry(reactors=tuple(reactors))
