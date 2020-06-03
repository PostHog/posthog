from django.db.models import Q, Exists, OuterRef
from .person import Person
import json
from typing import List, Optional, Union, Dict, Any


class Property:
    key: str
    operator: Optional[str]
    value: str
    type: str

    def __init__(self, key: str, value: str, operator: Optional[str]=None, type: Optional[str]=None) -> None:
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type if type else 'event'

    def __repr__(self):
        return 'Property({}: {}{}={})'.format(
            self.type,
            self.key,
            '__{}'.format(self.operator) if self.operator else '',
            self.value
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'value': self.value,
            'operator': self.operator,
            'type': self.type
        }

    def _parse_value(self, value: Union[int, str]) -> Union[int, str, bool]:
        if value == 'true':
            return True
        if value == 'false':
            return False
        if isinstance(value, int):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def property_to_Q(self) -> Q:
        value = self._parse_value(self.value)
        if self.operator == 'is_not':
            return Q(~Q(**{'properties__{}'.format(self.key): value}) | ~Q(properties__has_key=self.key))
        if self.operator == 'not_icontains':
            return Q(~Q(**{'properties__{}__icontains'.format(self.key): value}) | ~Q(properties__has_key=self.key))
        if self.operator == 'is_set':
            return Q(**{'properties__{}__isnull'.format(self.key): not value})
        return Q(**{'properties__{}{}'.format(self.key, '__{}'.format(self.operator) if self.operator else ''): value})

class PropertyMixin:
    properties: List[Property] = []

    def properties_to_Q(self, is_person_query: bool=False) -> Q:
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

        person_properties = [prop for prop in self.properties if prop.type == 'person']
        if len(person_properties) > 0:
            person_Q = Q()
            for property in person_properties:
                person_Q &= property.property_to_Q()
            filters &= Q(Exists(
                Person.objects.filter(
                    person_Q,
                    id=OuterRef('person_id'),
                ).only('pk')
            ))

        for property in [prop for prop in self.properties if prop.type == 'event']:
            filters &= property.property_to_Q()

        element_properties = [prop for prop in self.properties if prop.type == 'elements']
        if len(element_properties) > 0:
            from .event import Event
            filters &= Q(Exists(
                    Event.objects\
                    .filter(pk=OuterRef('id'))\
                    .filter_by_element({
                        item.key: item.value for item in element_properties
                    })
                ))

        return filters

    def _parse_properties(self, properties: Optional[Any]) -> List[Property]:
        if isinstance(properties, list):
            return [Property(**property) for property in properties]
        if not properties:
            return []

        # old style dict properties
        ret = []
        for key, value in properties.items():
            key_split = key.split('__')
            ret.append(Property(
                key=key_split[0],
                value=value,
                operator=key_split[1] if len(key_split) > 1 else None,
                type='event'
            ))
        return ret