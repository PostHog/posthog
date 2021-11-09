import pytest
from rest_framework.exceptions import ValidationError

from posthog.models.filters.mixins.groups import validate_group_type_index


def test_validate_group_type_index():
    validate_group_type_index("field", None)
    validate_group_type_index("field", 0)
    validate_group_type_index("field", 2)
    validate_group_type_index("field", 3)
    validate_group_type_index("field", 4)

    with pytest.raises(ValidationError):
        validate_group_type_index("field", 5)
    with pytest.raises(ValidationError):
        validate_group_type_index("field", "another_type")
    with pytest.raises(ValidationError):
        validate_group_type_index("field", -1)
    with pytest.raises(ValidationError):
        validate_group_type_index("field", None, required=True)
