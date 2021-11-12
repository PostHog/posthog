import pytest
from rest_framework.exceptions import ValidationError

from posthog.models.filters.utils import validate_group_type_index


def test_validate_group_type_index():
    assert validate_group_type_index("field", None) == None
    assert validate_group_type_index("field", 0) == 0
    assert validate_group_type_index("field", 2) == 2
    assert validate_group_type_index("field", 3) == 3
    assert validate_group_type_index("field", 4) == 4
    assert validate_group_type_index("field", "2") == 2

    with pytest.raises(ValidationError):
        validate_group_type_index("field", 5)
    with pytest.raises(ValidationError):
        validate_group_type_index("field", "6")
    with pytest.raises(ValidationError):
        validate_group_type_index("field", "another_type")
    with pytest.raises(ValidationError):
        validate_group_type_index("field", -1)
    with pytest.raises(ValidationError):
        validate_group_type_index("field", None, required=True)
