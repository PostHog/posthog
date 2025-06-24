from pydantic import BaseModel, Field, ValidationError
from enum import Enum

import yaml

from ee.session_recordings.session_summary import SummaryValidationError
from ee.session_recordings.session_summary.utils import strip_raw_llm_content


class _SeverityLevel(str, Enum):
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SessionGroupSummaryPattern(BaseModel):
    """Schema for validating individual pattern from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    pattern_name: str = Field(..., description="Human-readable name for the pattern", min_length=1)
    pattern_description: str = Field(..., description="Detailed description of the pattern", min_length=1)
    severity: _SeverityLevel = Field(..., description="Severity level of the pattern")
    indicators: list[str] = Field(..., description="List of indicators that signal this pattern", min_items=1)

    class Config:
        json_encoders = {_SeverityLevel: lambda v: v.value}


class SessionGroupSummaryPatternsList(BaseModel):
    """Schema for validating LLM output for patterns extraction"""

    patterns: list[SessionGroupSummaryPattern] = Field(..., description="List of patterns to validate", min_items=1)


class RawSessionGroupPatternAssignment(BaseModel):
    """Schema for validating individual pattern with events assigned from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    event_ids: list[str] = Field(..., description="List of event IDs assigned to this pattern", min_items=1)


class RawSessionGroupPatternAssignmentsList(BaseModel):
    """Schema for validating LLM output for patterns with events assigned"""

    patterns: list[RawSessionGroupPatternAssignment] = Field(
        ..., description="List of pattern assignments to validate", min_items=1
    )


def load_patterns_from_llm_content(raw_content: str, sessions_identifier: str) -> SessionGroupSummaryPatternsList:
    if not raw_content:
        raise SummaryValidationError(
            f"No LLM content found when extracting patterns for sessions {sessions_identifier}"
        )
    try:
        json_content: dict = yaml.safe_load(strip_raw_llm_content(raw_content))
    except Exception as err:
        raise SummaryValidationError(
            f"Error loading YAML content into JSON when extracting patterns for sessions {sessions_identifier}: {err}"
        ) from err
    # Validate the LLM output against the schema
    try:
        validated_patterns = SessionGroupSummaryPatternsList(**json_content)
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating LLM output against the schema when extracting patterns for sessions {sessions_identifier}: {err}"
        ) from err
    return validated_patterns


def load_pattern_assignments_from_llm_content(
    raw_content: str, sessions_identifier: str
) -> RawSessionGroupPatternAssignmentsList:
    if not raw_content:
        raise SummaryValidationError(
            f"No LLM content found when extracting pattern assignments for sessions {sessions_identifier}"
        )
    try:
        json_content: dict = yaml.safe_load(strip_raw_llm_content(raw_content))
    except Exception as err:
        raise SummaryValidationError(
            f"Error loading YAML content into JSON when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        ) from err
    # Validate the LLM output against the schema
    try:
        validated_assignments = RawSessionGroupPatternAssignmentsList(**json_content)
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating LLM output against the schema when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        ) from err
    return validated_assignments
