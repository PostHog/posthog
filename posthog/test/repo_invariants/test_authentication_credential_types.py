"""Every authentication class declares the credential type that its activity rows record.

`ActivityCredentialMixin.record_activity_actor` takes the type from `activity_credential_type`, so
the declaration and the recorded value cannot disagree. A class without a declaration raises
`AttributeError` when it records, and a class that never records leaves its rows `unattributed`.

A class that defines its own `authenticate` can verify a different credential from its parent, as
the delegated key classes do. So it declares its type again instead of inheriting it, even when the
value is the same.

To clear a violation, inherit `ActivityCredentialMixin`, set `activity_credential_type`, and call
`self.record_activity_actor(user, credential_id)` after every check of the credential passed. A new
kind of credential needs a new value in `DeclaredCredentialType`. See "Credential attribution" in
`docs/internal/activity-logging.md`.

    pytest posthog/test/repo_invariants/test_authentication_credential_types.py
"""

import ast
import functools
import importlib
from pathlib import Path
from typing import get_args

from rest_framework import authentication
from rest_framework.authentication import BaseAuthentication
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.views import APIView

from posthog.models.activity_logging.utils import ActivityCredentialMixin, DeclaredCredentialType

REPO_ROOT = Path(__file__).parents[3]
SCANNED_ROOTS = ("posthog", "ee", "products", "common")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"}
OWNED_MODULE_PREFIXES = tuple(f"{root}." for root in SCANNED_ROOTS)
DECLARED_TYPES = frozenset(get_args(DeclaredCredentialType))
# `ActivityLoggingMiddleware` records the session for any class that authenticates the session's
# user, so DRF's own session class records `session` too.
UNOWNED_ROUTE_CLASSES = frozenset({authentication.SessionAuthentication})


def _dotted_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _is_test_module(module: str) -> bool:
    return any(part in ("test", "tests") or part.startswith("test_") for part in module.split("."))


def _is_owned(cls: type) -> bool:
    return cls.__module__.startswith(OWNED_MODULE_PREFIXES) and not _is_test_module(cls.__module__)


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Attribute):
        return base.attr
    return base.id if isinstance(base, ast.Name) else ""


def _modules_that_subclass_an_authentication_class() -> set[str]:
    modules = set()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "Authentication" not in source:
                continue
            parts = path.relative_to(REPO_ROOT).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            if _is_test_module(module):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            if any(
                isinstance(node, ast.ClassDef)
                and any(_base_name(base).endswith("Authentication") for base in node.bases)
                for node in tree.body
            ):
                modules.add(module)
    return modules


def _subclasses(cls: type) -> set[type]:
    found: set[type] = set()
    for subclass in cls.__subclasses__():
        found |= {subclass, *_subclasses(subclass)}
    return found


@functools.cache
def _route_classes() -> frozenset[type]:
    # A view that sets no authentication classes uses DRF's default ones.
    classes: set[type] = set(APIView.authentication_classes)
    for _path, _method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        classes.update(getattr(view_class, "authentication_classes", None) or [])
    return frozenset(classes)


@functools.cache
def _owned_classes() -> tuple[type, ...]:
    # `__subclasses__()` sees only the classes of imported modules. The routes import the view
    # modules, and the source scan imports the modules that no route reaches.
    _route_classes()
    for module in sorted(_modules_that_subclass_an_authentication_class()):
        importlib.import_module(module)
    return tuple(sorted((cls for cls in _subclasses(BaseAuthentication) if _is_owned(cls)), key=_dotted_name))


def test_every_authentication_class_declares_a_credential_type() -> None:
    violations = []
    for cls in _owned_classes():
        name = _dotted_name(cls)
        if not issubclass(cls, ActivityCredentialMixin):
            violations.append(f"{name} does not inherit ActivityCredentialMixin")
            continue
        declared = getattr(cls, "activity_credential_type", None)
        if declared not in DECLARED_TYPES:
            violations.append(f"{name} declares {declared!r}, which is not a DeclaredCredentialType")
        elif "authenticate" in vars(cls) and "activity_credential_type" not in vars(cls):
            violations.append(f"{name} defines authenticate() but inherits activity_credential_type")

    assert not violations, "\n".join(violations)


def test_routes_use_only_authentication_classes_that_declare_a_credential_type() -> None:
    unowned = sorted(
        _dotted_name(cls) for cls in _route_classes() if not _is_owned(cls) and cls not in UNOWNED_ROUTE_CLASSES
    )

    assert not unowned, (
        "Routes use authentication classes that no PostHog module defines, so they declare no credential "
        "type. Wrap each one in a PostHog subclass:\n" + "\n".join(unowned)
    )


def test_every_credential_type_has_a_declaring_class() -> None:
    declared = {getattr(cls, "activity_credential_type", None) for cls in _owned_classes()}

    assert DECLARED_TYPES <= declared, (
        f"No authentication class declares {sorted(DECLARED_TYPES - declared)}. "
        "Remove the value from DeclaredCredentialType, or check that the walk still finds the classes."
    )
