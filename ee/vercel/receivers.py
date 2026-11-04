"""Vercel experimentation-item sync receivers.

Wired from ``EnterpriseConfig.ready()``. Kept apart from ``ee.vercel.integration`` so that
django.setup() does not import that module (and everything it reaches) in every process just
to connect three receivers; the integration is imported when a receiver actually fires.
"""

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.team import Team

from products.experiments.backend.facade.change_signals import connect_experiment_changed
from products.experiments.backend.facade.contracts import ExperimentChanged
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@receiver(post_save, sender=FeatureFlag)
def sync_feature_flag_experimentation_item(sender: Any, instance: FeatureFlag, created: bool, **kwargs: Any) -> None:
    from ee.vercel.integration import (  # noqa: PLC0415 — keeps the heavy dep off the import path
        VercelIntegration,
        _safe_vercel_sync,
    )

    if instance.deleted:
        _safe_vercel_sync(
            "delete feature flag from Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
            is_delete=True,
        )
    else:
        _safe_vercel_sync(
            "sync feature flag to Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.sync_feature_flag_to_vercel(instance, created),
        )


@receiver(post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender: Any, instance: FeatureFlag, **kwargs: Any) -> None:
    from ee.vercel.integration import (  # noqa: PLC0415 — keeps the heavy dep off the import path
        VercelIntegration,
        _safe_vercel_sync,
    )

    _safe_vercel_sync(
        "delete feature flag from Vercel",
        instance.pk,
        instance.team,
        lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
        is_delete=True,
    )


def sync_experiment_experimentation_item(sender: Any, change: ExperimentChanged, **kwargs: Any) -> None:
    from ee.vercel.integration import (  # noqa: PLC0415 — keeps the heavy dep off the import path
        VercelIntegration,
        _safe_vercel_sync,
    )

    team = Team.objects.get(id=change.team_id)
    # A soft delete and a hard delete both arrive with `deleted` set, and both remove the item from Vercel.
    if change.deleted:
        _safe_vercel_sync(
            "delete experiment from Vercel",
            change.experiment_id,
            team,
            lambda: VercelIntegration.delete_experiment_from_vercel(team, change.experiment_id),
            is_delete=True,
        )
    else:
        _safe_vercel_sync(
            "sync experiment to Vercel",
            change.experiment_id,
            team,
            lambda: VercelIntegration.sync_experiment_to_vercel(team, change),
        )


connect_experiment_changed(sync_experiment_experimentation_item, dispatch_uid="ee.vercel.sync_experiment")
