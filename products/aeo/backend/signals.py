"""Bump the stored-result version when a row that a set-level read counts is saved or deleted.

Bulk writes send no signal, so the code that makes them bumps the version itself: the runner, the
reconcile, the brand sync, the sentiment scorer, the prompt import and the fact backfill.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOEngineSetting, AEOPrompt
from products.aeo.backend.stored_results import bump_data_version_on_commit


@receiver([post_save, post_delete], sender=AEOBrand)
@receiver([post_save, post_delete], sender=AEOCitationCheck)
@receiver([post_save, post_delete], sender=AEOEngineSetting)
@receiver([post_save, post_delete], sender=AEOPrompt)
def bump_on_change(sender: type, instance: Any, **kwargs: Any) -> None:
    bump_data_version_on_commit(instance.team_id)
