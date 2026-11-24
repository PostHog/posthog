"""Bump the stored-result version when a prompt, a brand or an engine setting is saved or deleted.

Checks have no receiver on purpose. A delete receiver makes Django load and delete the rows of a
table one by one, which a team deletion cannot afford on a long check history. Every write to the
checks is a bulk write anyway, and the code that makes it bumps the version itself: the runner, the
reconcile, the sentiment scorer and the fact backfill. So do the brand sync and the prompt import.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from products.aeo.backend.models import AEOBrand, AEOEngineSetting, AEOPrompt
from products.aeo.backend.stored_results import bump_data_version_on_commit


@receiver([post_save, post_delete], sender=AEOBrand)
@receiver([post_save, post_delete], sender=AEOEngineSetting)
@receiver([post_save, post_delete], sender=AEOPrompt)
def bump_on_change(sender: type, instance: Any, **kwargs: Any) -> None:
    bump_data_version_on_commit(instance.team_id)
