"""
Shared utilities for Team extension models.

Team extensions are one-to-one models that extend the Team model with domain-specific
configuration. This module provides helpers to reduce boilerplate when creating them.

See README.md in this directory for full documentation on when and how to use extensions.
"""

import logging
import importlib
from typing import TYPE_CHECKING, Any, TypeVar

from django.db import IntegrityError, models, transaction

if TYPE_CHECKING:
    from posthog.models.team import Team

T = TypeVar("T", bound=models.Model)


def get_or_create_team_extension(
    team: "Team",
    model_class: type[T],
    defaults: dict[str, Any] | None = None,
) -> T:
    """
    Thread-safe get-or-create for team extension models.

    Example:
        config = get_or_create_team_extension(team, TeamRevenueAnalyticsConfig)
    """
    defaults = defaults or {}
    try:
        return model_class.objects.get(team=team)  # type: ignore[attr-defined]
    except model_class.DoesNotExist:  # type: ignore[attr-defined]
        try:
            with transaction.atomic():
                return model_class.objects.create(team=team, **defaults)  # type: ignore[attr-defined]
        except IntegrityError:
            # Race condition: another thread created it first
            return model_class.objects.get(team=team)  # type: ignore[attr-defined]


def register_team_extension_signal(
    model_class: type[T],
    defaults: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """
    Register a post_save signal that auto-creates the extension when a Team is created.

    Best-effort: the extension is also created lazily via get_or_create_team_extension
    if this fails.

    Example:
        register_team_extension_signal(TeamMyProductConfig, logger=logger)
    """
    from django.db.models.signals import post_save

    from posthog.models.team.team import Team

    defaults = defaults or {}
    _logger = logger or logging.getLogger(__name__)
    model_name = model_class.__name__

    def receiver_func(sender, instance: "Team", created: bool, **kwargs) -> None:  # noqa: ARG001
        if not created:
            return
        try:
            model_class.objects.get_or_create(team=instance, defaults=defaults)  # type: ignore[attr-defined]
        except Exception as e:
            _logger.warning(f"Error creating {model_name}: {e}")

    post_save.connect(receiver_func, sender=Team, dispatch_uid=f"create_{model_name.lower()}")


class TeamExtensionDescriptor:
    """
    TRANSITIONAL: Descriptor for lazy-loading Team extension models.

    Exists for backward compatibility with existing `team.<product>_config` accessors.
    Do NOT add new descriptors to Team — products should access their config via
    `get_or_create_team_extension()` directly. This avoids coupling the core Team model
    to product internals (see products/architecture.md for the target architecture).
    """

    def __init__(
        self,
        module_path: str,
        class_name: str,
        defaults: dict[str, Any] | None = None,
    ):
        self.module_path = module_path
        self.class_name = class_name
        self.defaults = defaults
        self._model_class: type | None = None
        self.attr_name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    @property
    def model_class(self) -> type[models.Model]:
        if self._model_class is None:
            module = importlib.import_module(self.module_path)
            self._model_class = getattr(module, self.class_name)
        return self._model_class

    def __get__(self, obj: "Team | None", objtype: type | None = None) -> Any:
        if obj is None:
            return self
        value = get_or_create_team_extension(obj, self.model_class, self.defaults)
        obj.__dict__[self.attr_name] = value
        return value
