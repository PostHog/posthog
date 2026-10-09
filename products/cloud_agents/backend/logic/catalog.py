"""What a caller can select for a run, and what it costs."""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from posthog.models import Team
from posthog.models.integration.claude_subscription import CLAUDE_SUBSCRIPTION_STORAGE_FEATURE_FLAG
from posthog.permissions import posthog_feature_flag_enabled

from products.tasks.backend.facade.model_catalogue import offered_model_choices
from products.tasks.backend.facade.pricing import estimate_cloud_agents_compute_usd, get_cloud_agents_rate_card
from products.tasks.backend.facade.run_config import RuntimeAdapter, get_default_model_for_runtime_adapter

from ..facade.contracts import CatalogDTO, EstimateDTO, LimitsDTO, ModelDTO, RateCardDTO
from ..facade.enums import InferenceMode, SizeName
from .limits import create_rate_per_hour, max_concurrent_runs
from .run_rows import size_spec

_USD_PLACES: Final = Decimal("0.0001")


def get_catalog(team_id: int) -> CatalogDTO:
    rate_card = get_cloud_agents_rate_card()
    default_model = get_default_model_for_runtime_adapter(RuntimeAdapter.CLAUDE.value)
    team = Team.objects.select_related("organization").get(id=team_id)
    subscription_storage_enabled = posthog_feature_flag_enabled(
        CLAUDE_SUBSCRIPTION_STORAGE_FEATURE_FLAG,
        team.api_token,
        organization_id=team.organization_id,
        team_id=team.id,
    )
    inference_modes = [
        mode for mode in InferenceMode if mode != InferenceMode.OWN_SUBSCRIPTION or subscription_storage_enabled
    ]
    return CatalogDTO(
        sizes=[size_spec(size) for size in SizeName],
        models=[
            ModelDTO(
                id=choice.model,
                name=choice.label,
                runtime_adapter=choice.runtime_adapter,
                is_default=choice.model == default_model,
            )
            for choice in offered_model_choices()
        ],
        inference_modes=inference_modes,
        rates=RateCardDTO(
            vcpu_hour_usd=rate_card.vcpu_hour_usd,
            memory_gib_hour_usd=rate_card.memory_gib_hour_usd,
            version=rate_card.version,
        ),
        limits=LimitsDTO(
            max_concurrent_runs=max_concurrent_runs(team_id),
            create_rate_per_hour=create_rate_per_hour(team_id),
        ),
    )


def estimate_cost(size: SizeName, minutes: int) -> EstimateDTO:
    """The compute price of a sandbox of this size that is up for `minutes`. Model usage is not in it."""
    spec = size_spec(size)
    estimate = estimate_cloud_agents_compute_usd(spec.vcpu, spec.memory_gib, minutes * 60)
    return EstimateDTO(
        size=size,
        minutes=minutes,
        price_per_hour_usd=spec.price_per_hour_usd,
        estimate_usd=estimate.quantize(_USD_PLACES),
    )
