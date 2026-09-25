from enum import Enum
from typing import Literal

from parameterized import parameterized
from pydantic import BaseModel, ConfigDict, ValidationError

from posthog.query_cache.schema_drift import is_schema_drift


class Mode(str, Enum):
    KNOWN = "known"


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["known"] = "known"
    mode: Mode = Mode.KNOWN
    count: int = 0


class TestIsSchemaDrift:
    @parameterized.expand(
        [
            ("field_added_by_a_newer_schema", {"field_added_later": 1}, True),
            ("literal_value_added_by_a_newer_schema", {"kind": "added_later"}, True),
            ("enum_member_added_by_a_newer_schema", {"mode": "added_later"}, True),
            ("drift_and_corruption_together", {"field_added_later": 1, "count": "nope"}, False),
            ("wrong_type", {"count": "nope"}, False),
        ]
    )
    def test_classifies_validation_error(self, _name: str, payload: dict, expected: bool) -> None:
        try:
            Response(**payload)
        except ValidationError as error:
            assert is_schema_drift(error) is expected
        else:
            raise AssertionError("payload was expected to fail validation")
