"""
Signal handlers that invalidate the per-team InsightVariable cache on writes.

Cache implementation lives in posthog/storage/insight_variable_cache.py.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

from posthog.models.insight_variable import InsightVariable
from posthog.storage.insight_variable_cache import invalidate_insight_variables_for_team


@receiver(post_save, sender=InsightVariable)
def insight_variable_saved(sender, instance: InsightVariable, **kwargs) -> None:
    team_id = instance.team_id
    transaction.on_commit(lambda: invalidate_insight_variables_for_team(team_id))


@receiver(post_delete, sender=InsightVariable)
def insight_variable_deleted(sender, instance: InsightVariable, **kwargs) -> None:
    team_id = instance.team_id
    transaction.on_commit(lambda: invalidate_insight_variables_for_team(team_id))
