from django.db.models import Q, Exists, OuterRef
from .person import Person
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

    def property_to_Q(self) -> Q:
        if self.operator == 'is_not':
            return Q(~Q(**{'properties__{}'.format(self.key): self.value}) | ~Q(properties__has_key=self.key))
        if self.operator == 'not_icontains':
            return Q(~Q(**{'properties__{}__icontains'.format(self.key): self.value}) | ~Q(properties__has_key=self.key))
        return Q(**{'properties__{}{}'.format(self.key, '__{}'.format(self.operator) if self.operator else ''): self.value})

class PropertyMixin:
    properties: List[Property] = []

    def properties_to_Q(self) -> Q:
        filters = Q()

        if len(self.properties) == 0:
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