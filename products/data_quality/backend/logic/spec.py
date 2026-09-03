"""The check-type extension point.

A check type is a ``CheckTypeSpec``: a Pydantic config model plus a compiler. Everything else is
derived. The JSON schema the API and MCP tools publish comes from ``model_json_schema()``, and
validation is ``model_validate``, so the config shape is declared once as typed fields instead of
being hand-written twice (as a schema and as a validator) and drifting.

Adding anomaly detection or unit tests later means adding a spec, not migrating the schema.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from ..facade.enums import CheckType
from .contracts import CheckPlan, SubjectRef
from .errors import CheckConfigError


class CheckConfig(BaseModel):
    """Base for every check type's config. Unknown keys are a mistake worth reporting, not ignoring."""

    model_config = ConfigDict(extra="forbid")


class NoConfig(CheckConfig):
    """For types whose column is the whole configuration."""


class CheckTypeSpec(ABC):
    """What every check type must provide.

    An ABC rather than a Protocol so a spec that forgets a field or gets a signature wrong fails at
    import, not on the first agent that tries to use it.
    """

    type_name: ClassVar[CheckType]
    config_model: ClassVar[type[CheckConfig]]
    requires_column: ClassVar[bool]
    description: ClassVar[str]

    @property
    def json_schema(self) -> dict[str, Any]:
        """Published by the check_types endpoint and the MCP tool docs. Generated, never written."""
        return self.config_model.model_json_schema()

    def parse_config(self, config: dict[str, Any]) -> CheckConfig:
        """Validate raw config into this type's model, or raise ``CheckConfigError``.

        Config only. The column is a separate axis, so callers that just need to read the config
        (resolving a related subject, say) do not have to supply one.
        """
        try:
            return self.config_model.model_validate(config or {})
        except ValidationError as err:
            raise CheckConfigError(f"Invalid config for a {self.type_name} check: {_first_problem(err)}")

    def validate(self, config: dict[str, Any], column_name: str) -> CheckConfig:
        """Everything a check needs to be compilable: a usable config and, where required, a column."""
        if self.requires_column and not column_name:
            raise CheckConfigError(f"A {self.type_name} check needs a column_name.")
        return self.parse_config(config)

    def coerce_to_column(self, config: CheckConfig, column_type: str | None) -> CheckConfig:
        """Normalize config values against the column's type. Identity for types that hold none.

        ``column_type`` is the raw ClickHouse type, or None when it could not be established.
        """
        return config

    def related_subject_ref(self, config: CheckConfig) -> tuple[str, str] | None:
        """The second subject this check needs resolved before it can compile, if any."""
        return None

    def referenced_table_names(self, config: CheckConfig) -> list[str]:
        """Warehouse names this check reads directly, besides its subject and related subject.

        Only ``custom_sql`` needs this -- its query names arbitrary tables. Every structured type
        reaches exactly its subject plus, via ``related_subject_ref``, one other, so the default is
        empty. Used to authorize every subject a check reads, since the worker executes with team
        scope only."""
        return []

    @abstractmethod
    def build(
        self,
        subject: SubjectRef,
        column_name: str,
        config: CheckConfig,
        related: SubjectRef | None = None,
    ) -> CheckPlan:
        """Select the rows that violate the assertion. The compiler aggregates over them."""


def _first_problem(err: ValidationError) -> str:
    problem = err.errors()[0]
    location = ".".join(str(part) for part in problem["loc"]) or "config"
    return f"{location}: {problem['msg']}"
