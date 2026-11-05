import time
from collections import defaultdict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)

BATCH_SIZE = 500
MAX_BATCHES_PER_TYPE = 20
TIME_BUDGET_SECONDS = 180


class OfflinePayloadRetention:
    def __init__(self) -> None:
        self.batches = 0
        self.item_payloads_expired = 0
        self.result_payloads_expired = 0
        self.budget_exhausted = False

    def _expire_batch(
        self,
        owner_model: type[OfflineExperimentItem] | type[OfflineEvaluationResult],
        payload_model: type[OfflineExperimentItemPayload] | type[OfflineEvaluationResultPayload],
        deadline: float,
    ) -> bool:
        cutoff = timezone.now()
        by_team: dict[int, list[UUID]] = defaultdict(list)
        candidates = (
            owner_model.objects.unscoped()
            .filter(payload_state=PayloadState.AVAILABLE, payload_expires_at__lte=cutoff)
            .order_by("payload_expires_at", "id")
            .values_list("id", "team_id")[:BATCH_SIZE]
        )
        for owner_id, team_id in candidates:
            by_team[team_id].append(owner_id)

        progressed = False
        for team_id, ids in by_team.items():
            if time.monotonic() >= deadline:
                self.budget_exhausted = True
                return progressed
            with transaction.atomic():
                owners = owner_model.objects.for_team(team_id).filter(
                    id__in=ids, payload_state=PayloadState.AVAILABLE, payload_expires_at__lte=cutoff
                )
                locked_ids = list(owners.select_for_update(skip_locked=True).values_list("id", flat=True))
                if not locked_ids:
                    continue
                deleted, _ = payload_model.objects.for_team(team_id).filter(pk__in=locked_ids).delete()
                owners.filter(id__in=locked_ids).update(payload_state=PayloadState.EXPIRED)
            self.batches += 1
            if payload_model is OfflineExperimentItemPayload:
                self.item_payloads_expired += deleted
            else:
                self.result_payloads_expired += deleted
            progressed = True
        return progressed

    def run(self) -> None:
        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        items_remaining = results_remaining = True
        for _ in range(MAX_BATCHES_PER_TYPE):
            for owner_model, payload_model, remaining in (
                (OfflineExperimentItem, OfflineExperimentItemPayload, items_remaining),
                (OfflineEvaluationResult, OfflineEvaluationResultPayload, results_remaining),
            ):
                if time.monotonic() >= deadline:
                    self.budget_exhausted = True
                    return
                if remaining:
                    progressed = self._expire_batch(owner_model, payload_model, deadline)
                    if owner_model is OfflineExperimentItem:
                        items_remaining = progressed
                    else:
                        results_remaining = progressed
            if not items_remaining and not results_remaining:
                return
        self.budget_exhausted = True
