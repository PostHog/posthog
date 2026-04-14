from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from posthog.models import Team, User

Q = TypeVar("Q", bound=BaseModel)


class SupportsQueryValidation(Protocol[Q]):
    query: Q
    team: Team
    user: User | None


@dataclass(frozen=True)
class QueryValidationContext(Generic[Q]):
    query: Q
    team: Team
    user: User | None
    runner: SupportsQueryValidation[Q]


class QueryValidationRule(Protocol[Q]):
    def validate(self, context: QueryValidationContext[Q]) -> None: ...


def run_validation_rules(
    rules: Sequence[QueryValidationRule[Q]],
    context: QueryValidationContext[Q],
) -> None:
    for rule in rules:
        rule.validate(context)
