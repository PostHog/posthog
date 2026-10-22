from typing import Any

from ...facade.enums import CheckType, SubjectType
from ..contracts import BulkQuestionPlan, SubjectRef
from ..errors import CheckConfigError
from ..jev_question import QuestionConfig
from ..spec import CheckConfig, CheckTypeSpec


class QuestionSpec(CheckTypeSpec):
    type_name = CheckType.QUESTION
    config_model = QuestionConfig
    requires_column = False
    subject_types = frozenset({SubjectType.TABLE})
    description = "Asks a yes/no question of every row; yes is expected. Warning-only."

    def validate(self, config: dict[str, Any], column_name: str) -> QuestionConfig:
        parsed = QuestionConfig.model_validate(super().validate(config, column_name))
        try:
            parsed.input_columns(column_name)
        except ValueError as error:
            raise CheckConfigError(str(error)) from error
        return parsed

    def build(
        self, subject: SubjectRef, column_name: str, config: CheckConfig, related: SubjectRef | None = None
    ) -> BulkQuestionPlan:
        return BulkQuestionPlan(subject=subject, column_name=column_name, config=QuestionConfig.model_validate(config))


SPEC = QuestionSpec()
