from datetime import datetime
from typing import Callable, Optional, Union

from django.utils import timezone

from posthog.constants import DATE_FROM, DATE_TO, STICKINESS_DAYS
from posthog.models.entity import Entity
from posthog.models.filters.mixins.common import BaseParamMixin, DateMixin, EntitiesMixin, IntervalMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.team import Team
from posthog.utils import relative_date_parse


class SelectedIntervalMixin(BaseParamMixin):
    @cached_property
    def selected_interval(self) -> int:
        return int(self._data.get(STICKINESS_DAYS, "0"))

    @include_dict
    def selected_interval_to_dict(self):
        return {"selected_interval": self.selected_interval} if self.selected_interval else {}


class StickinessDateMixin(DateMixin):
    get_earliest_timestamp: Callable
    team: Team

    @cached_property
    def _date_from(self) -> Optional[Union[str, datetime]]:
        if not self.team or not self.get_earliest_timestamp:
            raise AttributeError("StickinessDateMixin requires team and get_earliest_timestamp to be provided")

        _date_from = self._data.get(DATE_FROM, None)
        if _date_from == "all":
            return self.get_earliest_timestamp(team_id=self.team.pk)
        elif _date_from:
            return _date_from
        else:
            return relative_date_parse("-7d")

    @cached_property
    def _date_to(self) -> Optional[Union[str, datetime]]:
        return self._data.get(DATE_TO)


class TotalIntervalsDerivedMixin(IntervalMixin, StickinessDateMixin):
    """
    Properties
    -----------
    - total_intervals
    - date_from (inherited)
    - date_to (inherited)
    - interval (inherited)
    """

    @cached_property
    def total_intervals(self) -> int:
        _num_intervals = 0
        _total_seconds = (self.date_to - self.date_from).total_seconds()
        if self.interval == "minute":
            _num_intervals = int(divmod(_total_seconds, 60)[0])
        elif self.interval == "hour":
            _num_intervals = int(divmod(_total_seconds, 3600)[0])
        elif self.interval == "day":
            _num_intervals = int(divmod(_total_seconds, 86400)[0])
        elif self.interval == "week":
            _num_intervals = (self.date_to - self.date_from).days // 7
        elif self.interval == "month":
            _num_intervals = (self.date_to.year - self.date_from.year) + (self.date_to.month - self.date_from.month)
        else:
            raise ValueError(f"{self.interval} not supported")
        _num_intervals += 2
        return _num_intervals


class EntityIdMixin(BaseParamMixin):
    @cached_property
    def target_entity_id(self) -> Optional[str]:
        return self._data.get("entityId", None)

    @include_dict
    def entity_id_to_dict(self):
        return {"entity_id": self.target_entity_id} if self.target_entity_id else {}


class EntityTypeMixin(BaseParamMixin):
    @cached_property
    def target_entity_type(self) -> Optional[str]:
        return self._data.get("type", None)

    @include_dict
    def entity_type_to_dict(self):
        return {"entity_type": self.target_entity_type} if self.target_entity_type else {}


class TargetEntityDerivedMixin(EntitiesMixin, EntityTypeMixin, EntityIdMixin):
    """
    Properties
    -----------
    - target_entity
    - entity_type (inherited)
    - entity_id (inherited)
    - entities (inherited)
    - actions (inherited)
    - events (inherited)
    """

    @cached_property
    def target_entity(self) -> Entity:
        if self.entities:
            return self.entities[0]
        elif self.target_entity_id and self.target_entity_type:
            return Entity({"id": self.target_entity_id, "type": self.target_entity_type})
        else:
            raise ValueError("An entity must be provided for stickiness target entity to be determined")
