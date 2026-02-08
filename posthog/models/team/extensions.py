"""
Shared utilities for Team extension models.

Team extensions are one-to-one models that extend the Team model with domain-specific
configuration. This module provides helpers to reduce boilerplate when creating them.

See README.md in this directory for full documentation on when and how to use extensions.
"""

import logging
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

    Args:
        team: The Team instance to get/create the extension for
        model_class: The extension model class (must have a OneToOneField to Team)
        defaults: Optional dict of default values for creation

    Returns:
        The extension model instance

    Example:
        config = get_or_create_team_extension(team, TeamRevenueAnalyticsConfig)
    """
    defaults = defaults or {}
    try:
        return model_class.objects.get(team=team)
    except model_class.DoesNotExist:
        try:
            with transaction.atomic():
                return model_class.objects.create(team=team, **defaults)
        except IntegrityError:
            # Race condition: another thread created it first
            return model_class.objects.get(team=team)


def create_extension_signal_receiver(
    model_class: type[T],
    defaults: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
):
    """
    Factory for post_save signal receivers that auto-create extension models.

    Creates a signal receiver function that creates the extension when a Team is created.
    This is best-effort - the extension can also be created lazily via the Team accessor.

    Args:
        model_class: The extension model class
        defaults: Optional dict of default values for creation
        logger: Optional logger for warning messages (uses module logger if not provided)

    Returns:
        A signal receiver function suitable for use with @receiver(post_save, sender=Team)

    Example:
        from django.db.models.signals import post_save
        from django.dispatch import receiver
        from posthog.models.team import Team

        @receiver(post_save, sender=Team)
        def create_my_config(sender, instance, created, **kwargs):
            return _create_my_config(sender, instance, created, **kwargs)

        _create_my_config = create_extension_signal_receiver(
            MyTeamConfig,
            defaults={"some_field": "default_value"},
        )
    """
    defaults = defaults or {}
    _logger = logger or logging.getLogger(__name__)
    model_name = model_class.__name__

    def receiver_func(sender, instance: "Team", created: bool, **kwargs) -> None:  # noqa: ARG001
        if not created:
            return
        try:
            model_class.objects.get_or_create(team=instance, defaults=defaults)
        except Exception as e:
            _logger.warning(f"Error creating {model_name}: {e}")

    return receiver_func
