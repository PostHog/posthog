import functools
import threading
from typing import Any

import pytest
from unittest.mock import NonCallableMock, patch

from django.db import transaction

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from posthog.models import User

_authenticated_classes: set[type] = set()
_problems: list[str] = []
_replayed_classes: set[type] = set()
_state = threading.local()


def install() -> None:
    for cls in _subclasses(BaseAuthentication):
        _wrap(cls)
    BaseAuthentication.__init_subclass__ = classmethod(lambda cls, **kwargs: _wrap(cls))  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]


def covers_authentication(*classes: type) -> pytest.MarkDecorator:
    return pytest.mark.covers_authentication.with_args(*classes)


def start_test() -> None:
    _authenticated_classes.clear()
    _problems.clear()


def finish_test(covered_classes: tuple[type, ...]) -> list[str]:
    problems = list(_problems)
    for cls in covered_classes:
        if not any(issubclass(seen, cls) for seen in _authenticated_classes):
            problems.append(f"{cls.__qualname__} did not authenticate a request in this test.")
    return problems


def _subclasses(cls: type) -> set[type]:
    found: set[type] = set()
    for subclass in cls.__subclasses__():
        found |= {subclass, *_subclasses(subclass)}
    return found


def _wrap(cls: type) -> None:
    original = vars(cls).get("authenticate")
    if original is None or getattr(original, "_checked", False):
        return

    @functools.wraps(original)
    def authenticate(self: BaseAuthentication, request: Any) -> Any:
        if getattr(_state, "active", False):
            return original(self, request)
        _state.active = True
        try:
            result = original(self, request)
            if result is not None:
                _authenticated_classes.add(type(self))
                _replay(type(self), request, result[0])
            return result
        finally:
            _state.active = False

    authenticate._checked = True  # type: ignore[attr-defined]
    cls.authenticate = authenticate  # type: ignore[attr-defined]


def _attempt(authentication_class: type, request: Any) -> tuple[Any, Exception | None]:
    try:
        result = authentication_class().authenticate(request)
    except Exception as error:
        return None, error
    return (result[0] if result else None), None


def _replay(authentication_class: type, request: Any, user: Any) -> None:
    if not isinstance(user, User) or isinstance(user, NonCallableMock) or user.pk is None:
        return
    name = authentication_class.__qualname__
    if not user.is_active:
        _problems.append(f"{name}.authenticate() accepted a deactivated user.")
        return
    if authentication_class in _replayed_classes:
        return
    _replayed_classes.add(authentication_class)

    with transaction.atomic():
        try:
            User.objects.filter(pk=user.pk).update(is_active=False)
            user.is_active = False
            principal, _error = _attempt(authentication_class, request)
        finally:
            user.is_active = True
            transaction.set_rollback(True)
    if isinstance(principal, User):
        _problems.append(f"{name}.authenticate() accepted a deactivated user.")

    with transaction.atomic(), patch("posthog.auth.security_access_refused", return_value=True):
        try:
            principal, error = _attempt(authentication_class, request)
        finally:
            transaction.set_rollback(True)
    if isinstance(principal, User):
        _problems.append(f"{name}.authenticate() accepted a blocked account.")
    elif isinstance(error, AuthenticationFailed) and error.get_codes() != "access_blocked":
        _problems.append(f"{name}.authenticate() refused a blocked account without the access_blocked code.")
