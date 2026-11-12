import re
from collections.abc import Iterable
from typing import Any

from django.db.models import Case, CharField, F, Func, Q, Value, When
from django.db.models.functions import Length, Lower
from django.db.models.lookups import Exact, In, Regex

from posthog.models.file_system.constants import WORKFLOW_FILE_SYSTEM_TYPES

# A UUID-keyed object can be filed under any spelling of its id, such as uppercase or without hyphens,
# because rows written before refs were canonicalized kept what the client sent. Every query that
# matches a row to its object compares this key, the 32 lowercase hex digits, and never the stored
# text. `uuid_ref_key` and `uuid_ref_key_expression` must compute the same key: one runs in Python,
# the other in SQL. A ref outside these spellings has no key, so it names no object.
_PREFIX = "urn:uuid:"
_SPELLING = r"\{?[0-9A-Fa-f-]*\}?"
_DRESSING = r"[{}-]"


def uuid_ref_key(ref: str | None) -> str | None:
    if not ref:
        return None
    body = ref.removeprefix(_PREFIX)
    if not re.fullmatch(_SPELLING, body):
        return None
    digits = re.sub(_DRESSING, "", body)
    return digits.lower() if len(digits) == 32 else None


def _regexp_replace(expression: Any, pattern: str, flags: str = "") -> Func:
    arguments = [expression, Value(pattern), Value("")]
    if flags:
        arguments.append(Value(flags))
    return Func(*arguments, function="REGEXP_REPLACE", output_field=CharField())


def uuid_ref_key_expression(ref: Any = "ref") -> Case:
    expression = F(ref) if isinstance(ref, str) else ref
    body = _regexp_replace(expression, f"^{_PREFIX}")
    digits = _regexp_replace(body, _DRESSING, "g")
    return Case(
        When(Regex(body, f"^{_SPELLING}$") & Exact(Length(digits), 32), then=Lower(digits)),
        default=None,
        output_field=CharField(),
    )


def uuid_refs_q(refs: Iterable[str], field: str = "ref") -> Q:
    """Rows whose `field` names one of these UUID-keyed objects, in any spelling of its id."""
    refs = set(refs)
    keys = sorted({key for ref in refs if (key := uuid_ref_key(ref))})
    exact = Q(**{f"{field}__in": sorted(refs)})
    return exact | Q(In(uuid_ref_key_expression(field), keys)) if keys else exact


def file_refs_q(file_type: str | Iterable[str], refs: Iterable[str]) -> Q:
    """Rows that name one of these objects. Workflow and template rows match in any spelling of the id."""
    types = {file_type} if isinstance(file_type, str) else set(file_type)
    if types & WORKFLOW_FILE_SYSTEM_TYPES:
        return uuid_refs_q(refs)
    unique = list(dict.fromkeys(refs))
    return Q(ref=unique[0]) if len(unique) == 1 else Q(ref__in=unique)


def same_file_ref(file_type: str | Iterable[str], ref: Any, other: Any) -> Q:
    """`ref` and `other`, two expressions, name the same object of `file_type`."""
    types = {file_type} if isinstance(file_type, str) else set(file_type)
    if types & WORKFLOW_FILE_SYSTEM_TYPES:
        return Q(Exact(uuid_ref_key_expression(ref), uuid_ref_key_expression(other)))
    return Q(Exact(F(ref) if isinstance(ref, str) else ref, other))
