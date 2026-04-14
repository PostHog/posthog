from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from posthog.models import Team, User

Q = TypeVar("Q", bound=BaseModel)
Q_co = TypeVar("Q_co", bound=BaseModel, covariant=True)
Q_contra = TypeVar("Q_contra", bound=BaseModel, contravariant=True)


class SupportsQueryValidation(Protocol[Q_co]):
    @property
    def query(self) -> Q_co: ...

    @property
    def team(self) -> Team: ...

    @property
    def user(self) -> User | None: ...


@dataclass(frozen=True)
class QueryValidationContext(Generic[Q_co]):
    query: Q_co
    team: Team
    user: User | None
    runner: SupportsQueryValidation[Q_co]


class QueryValidationRule(Protocol[Q_contra]):
    def validate(self, context: QueryValidationContext[Q_contra]) -> None: ...


def run_validation_rules(
    rules: Sequence[QueryValidationRule[Q]],
    context: QueryValidationContext[Q],
) -> None:
    for rule in rules:
        rule.validate(context)
