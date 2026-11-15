from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, NotRequired, TypedDict

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.organization import ProductFeature


class FeatureEntry(TypedDict):
    key: str
    limit: NotRequired[int | None]
    unit: NotRequired[str | None]


class EntitlementSnapshotEntry(TypedDict):
    key: str
    limit: int | None
    unit: str | None


@frozen
class EntitlementFeature:
    key: str
    limit: int | None = None
    unit: str | None = None


@frozen
class Entitlements:
    features: tuple[EntitlementFeature, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.features, key=lambda feature: feature.key))
        if len({feature.key for feature in ordered}) != len(ordered):
            raise ValueError("Duplicate entitlement feature key")
        object.__setattr__(self, "features", ordered)

    @classmethod
    def from_features(
        cls, features: Iterable[FeatureEntry | EntitlementSnapshotEntry | "ProductFeature"]
    ) -> "Entitlements":
        return cls(
            features=tuple(
                EntitlementFeature(key=feature["key"], limit=feature.get("limit"), unit=feature.get("unit"))
                for feature in features
            )
        )

    def to_snapshot(self) -> list[EntitlementSnapshotEntry]:
        return [{"key": feature.key, "limit": feature.limit, "unit": feature.unit} for feature in self.features]

    def has(self, key: str) -> bool:
        return any(feature.key == key for feature in self.features)

    def limit(self, key: str) -> int | None:
        return next((feature.limit for feature in self.features if feature.key == key), None)

    def keys(self) -> frozenset[str]:
        return frozenset(feature.key for feature in self.features)

    def restricted_to(self, keys: Iterable[str]) -> "Entitlements":
        selected = frozenset(keys)
        return Entitlements(features=tuple(feature for feature in self.features if feature.key in selected))


@frozen
class EntitlementChange:
    organization_id: str
    previous: Entitlements | None
    current: Entitlements


@frozen
class EntitlementReactor:
    key: str
    feature_keys: frozenset[str]
    react: Callable[[EntitlementChange], None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_keys", frozenset(self.feature_keys))
