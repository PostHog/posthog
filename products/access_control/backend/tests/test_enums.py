from typing import get_args

from products.access_control.backend.facade.enums import (
    ResolvedAccessSource,
    ResolvedAccessSourceSubject,
    ResolvedAccessSourceSubjectValue,
    ResolvedAccessSourceValue,
)


def test_resolved_access_choices_match_the_dataclass_literals() -> None:
    assert set(ResolvedAccessSource.values) == set(get_args(ResolvedAccessSourceValue))
    assert set(ResolvedAccessSourceSubject.values) == set(get_args(ResolvedAccessSourceSubjectValue))
