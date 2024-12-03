import json
from typing import Optional, Literal, Union

from posthog.hogql import ast
from posthog.constants import PERSON_UUID_FILTER, SESSION_RECORDINGS_FILTER_IDS, PropertyOperatorType
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyGroup


class PersonUUIDMixin(BaseParamMixin):
    @cached_property
    def person_uuid(self) -> Optional[str]:
        return self._data.get(PERSON_UUID_FILTER, None)


class SessionRecordingsMixin(PropertyMixin, BaseParamMixin):
    @cached_property
    def order(self) -> str:
        return self._data.get("order", "start_time")

    @cached_property
    def console_log_filters(self) -> PropertyGroup:
        property_group = self._parse_data(key="console_log_filters")
        property_group.type = self.property_operand
        return property_group

    @cached_property
    def property_operand(self) -> PropertyOperatorType:
        return PropertyOperatorType.AND if self._operand == "AND" else PropertyOperatorType.OR

    @cached_property
    def ast_operand(self) -> type[Union[ast.And, ast.Or]]:
        return ast.And if self._operand == "AND" else ast.Or

    @cached_property
    def _operand(self) -> Literal["AND"] | Literal["OR"]:
        return self._data.get("operand", "AND")

    @cached_property
    def session_ids(self) -> Optional[list[str]]:
        # Can be ['a', 'b'] or "['a', 'b']" or "a,b"
        session_ids_str = self._data.get(SESSION_RECORDINGS_FILTER_IDS, None)

        if session_ids_str is None:
            return None

        if isinstance(session_ids_str, list):
            recordings_ids = session_ids_str
        elif isinstance(session_ids_str, str):
            if session_ids_str.startswith("["):
                recordings_ids = json.loads(session_ids_str)
            else:
                recordings_ids = session_ids_str.split(",")

        if all(isinstance(recording_id, str) for recording_id in recordings_ids):
            # Sort for stable queries
            return sorted(recordings_ids)

        # If the property is at all present, we assume that the user wants to filter by it
        return []

    @cached_property
    def having_predicates(self) -> PropertyGroup:
        return self._parse_data(key="having_predicates")
