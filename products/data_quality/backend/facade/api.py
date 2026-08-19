"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from ..logic.checks import (
    checks_for_subject,
    ensure_name_available,
    soft_delete_check,
    start_check_suite,
    subject_health,
    update_check,
    upsert_check,
    validate_check,
)
from ..logic.compiler import compile_check, related_subject_ref
from ..logic.config import get_gate_config, set_gate_materialization_on_checks
from ..logic.contracts import CompiledCheck, SubjectRef
from ..logic.errors import CheckConfigError, SubjectUnresolvableError
from ..logic.health import CheckStatusRow, roll_up_health
from ..logic.notifications import notify_materialization_blocked
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.subject_access import denied_subject_names, is_subject_denied, referenced_subject_names
from ..logic.subjects import resolve_subject
from ..logic.triggers import materialization_audit_mode as quality_audit_mode
from .contracts import CheckTypeInfo

__all__ = [
    "CheckConfigError",
    "CheckStatusRow",
    "CheckTypeInfo",
    "CompiledCheck",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "checks_for_subject",
    "compile_check",
    "compute_fingerprint",
    "denied_subject_names",
    "ensure_name_available",
    "from_config_entry",
    "get_gate_config",
    "is_subject_denied",
    "list_check_types",
    "notify_materialization_blocked",
    "quality_audit_mode",
    "referenced_subject_names",
    "related_subject_ref",
    "resolve_subject",
    "roll_up_health",
    "set_gate_materialization_on_checks",
    "soft_delete_check",
    "start_check_suite",
    "subject_health",
    "to_config_entry",
    "update_check",
    "upsert_check",
    "validate_check",
]
