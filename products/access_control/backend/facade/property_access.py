import json
import hashlib
from collections.abc import Collection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.property_access_types import RestrictedProperty


def sort_restricted_properties(restrictions: Collection["RestrictedProperty"]) -> list["RestrictedProperty"]:
    return sorted(
        restrictions,
        key=lambda restriction: (
            restriction.name,
            restriction.property_type,
            restriction.group_type_index if restriction.group_type_index is not None else -1,
        ),
    )


def restriction_fingerprint(restrictions: Collection["RestrictedProperty"]) -> str:
    metadata = [
        (restriction.name, restriction.property_type, restriction.group_type_index)
        for restriction in sort_restricted_properties(restrictions)
    ]
    return hashlib.sha256(json.dumps(metadata).encode()).hexdigest()
