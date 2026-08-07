"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It re-exports the
logic surface and model classes so the isolation boundary stays clean: presentation never reaches
into ``logic`` or ``models`` directly.
"""

from ..logic.compiler import compile_check, related_subject_ref
from ..logic.contracts import CheckPlan, CompiledCheck, Evaluation, SubjectRef
from ..logic.errors import CheckConfigError, SubjectUnresolvableError
from ..logic.registry import UnknownCheckTypeError, all_specs, get_spec
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.spec import CheckConfig, CheckTypeSpec
from ..logic.subjects import resolve_subject
from .models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun

__all__ = [
    "CheckConfig",
    "CheckConfigError",
    "CheckPlan",
    "CheckTypeSpec",
    "CompiledCheck",
    "DataQualityCheck",
    "DataQualityCheckRun",
    "DataQualitySuiteRun",
    "Evaluation",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "all_specs",
    "compile_check",
    "compute_fingerprint",
    "from_config_entry",
    "get_spec",
    "related_subject_ref",
    "resolve_subject",
    "to_config_entry",
]
