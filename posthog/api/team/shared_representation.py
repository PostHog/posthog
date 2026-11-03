from collections.abc import Callable
from typing import Any, ClassVar

from rest_framework import serializers
from rest_framework.fields import SkipField
from rest_framework.relations import PKOnlyObject

from posthog.caching.team_representation_cache import (
    get_team_representation,
    set_team_representation,
    team_representation_cache_key,
)


class SharedTeamRepresentationMixin(serializers.Serializer):
    """Takes every field outside `per_request_fields` from a cache that all callers of one team share.

    A field belongs in `per_request_fields` when its value depends on the caller or the request, or comes from data
    that the cache invalidation in `posthog/caching/team_representation_cache.py` does not track.
    The instance is a Team or a Project. A project's pk is the pk of its passthrough team, so both key on the team.
    """

    per_request_fields: ClassVar[frozenset[str]] = frozenset()

    def finish_shared_representation(self, instance: Any, representation: dict[str, Any]) -> None:
        """Adjusts the shared part before it is cached. It must not depend on the caller."""

    def field_attribute_source(self, instance: Any, field_name: str) -> Any:
        """The object a field reads its value from."""
        return instance

    def to_representation(self, instance: Any) -> dict[str, Any]:
        key = team_representation_cache_key(type(self).__name__, instance.pk, str(instance.organization_id))
        shared = get_team_representation(key)
        if shared is None:
            shared = self._represent_fields(instance, lambda name: name not in self.per_request_fields)
            self.finish_shared_representation(instance, shared)
            # Ingestion sets `ingested_event` with raw SQL, which sends no signal. It only changes from false to
            # true, so an entry is written only once it is true.
            if shared.get("ingested_event"):
                set_team_representation(key, shared)
        representation = {**shared, **self._represent_fields(instance, lambda name: name in self.per_request_fields)}
        return {
            field.field_name: representation[field.field_name]
            for field in self._readable_fields
            if field.field_name in representation
        }

    def _represent_fields(self, instance: Any, include: Callable[[str], bool]) -> dict[str, Any]:
        # Mirrors rest_framework's Serializer.to_representation, for a subset of the fields.
        representation: dict[str, Any] = {}
        for field in self._readable_fields:
            name = field.field_name
            assert name is not None
            if not include(name):
                continue
            try:
                attribute = field.get_attribute(self.field_attribute_source(instance, name))
            except SkipField:
                continue
            check_for_none = attribute.pk if isinstance(attribute, PKOnlyObject) else attribute
            representation[name] = None if check_for_none is None else field.to_representation(attribute)
        return representation
