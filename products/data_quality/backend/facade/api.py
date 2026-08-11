"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from ..logic.compiler import compile_check, related_subject_ref
from ..logic.contracts import CompiledCheck, SubjectRef
from ..logic.errors import CheckConfigError, SubjectUnresolvableError
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.subjects import resolve_subject
from .contracts import CheckTypeInfo

__all__ = [
    "CheckConfigError",
    "CheckTypeInfo",
    "CompiledCheck",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "compile_check",
    "compute_fingerprint",
    "from_config_entry",
    "list_check_types",
    "related_subject_ref",
    "resolve_subject",
    "to_config_entry",
]
