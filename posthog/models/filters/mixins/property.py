import json
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models import Exists, OuterRef, Q

from posthog.constants import PROPERTIES
from posthog.models.filters.mixins.base import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.person import Person
from posthog.models.property import Property


class PropertyMixin(BaseParamMixin):
    @cached_property
    def properties(self) -> List[Property]:
        _props = self._data.get(PROPERTIES)
        loaded_props = json.loads(_props) if isinstance(_props, str) else _props
        return self._parse_properties(loaded_props)

    def properties_to_Q(self, team_id: int, is_person_query: bool = False) -> Q:
        """
        Converts a filter to Q, for use in Django ORM .filter()
        If you're filtering a Person QuerySet, use is_person_query to avoid doing an unnecessary nested loop
        """
        filters = Q()

        if len(self.properties) == 0:
            return filters

        if is_person_query:
            for property in self.properties:
                filters &= property.property_to_Q()
            return filters

        person_properties = [prop for prop in self.properties if prop.type == "person"]
        if len(person_properties) > 0:
            person_Q = Q()
            for property in person_properties:
                person_Q &= property.property_to_Q()
            filters &= Q(Exists(Person.objects.filter(person_Q, id=OuterRef("person_id"),).only("pk")))

        for property in [prop for prop in self.properties if prop.type == "event"]:
            filters &= property.property_to_Q()

        # importing from .event and .cohort below to avoid importing from partially initialized modules

        element_properties = [prop for prop in self.properties if prop.type == "element"]
        if len(element_properties) > 0:
            from posthog.models.event import Event

            filters &= Q(
                Exists(
                    Event.objects.filter(pk=OuterRef("id"))
                    .filter(
                        **Event.objects.filter_by_element(
                            {item.key: item.value for item in element_properties}, team_id=team_id,
                        )
                    )
                    .only("id")
                )
            )

        cohort_properties = [prop for prop in self.properties if prop.type == "cohort"]
        if len(cohort_properties) > 0:
            from posthog.models.cohort import CohortPeople

            for item in cohort_properties:
                if item.key == "id":
                    filters &= Q(
                        Exists(
                            CohortPeople.objects.filter(
                                cohort_id=int(item.value), person_id=OuterRef("person_id"),
                            ).only("id")
                        )
                    )
        return filters

    def _parse_properties(self, properties: Optional[Any]) -> List[Property]:
        if isinstance(properties, list):
            return [Property(**property) for property in properties]
        if not properties:
            return []

        # old style dict properties
        ret = []
        for key, value in properties.items():
            key_split = key.split("__")
            ret.append(
                Property(
                    key=key_split[0], value=value, operator=key_split[1] if len(key_split) > 1 else None, type="event",
                )
            )
        return ret

    @include_dict
    def properties_to_dict(self):
        return {"properties": [prop.to_dict() for prop in self.properties]} if self.properties else {}
