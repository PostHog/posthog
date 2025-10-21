"""Entity configurations for vectorization."""

from datetime import datetime
from typing import Any

from django.db.models import F, Q

from posthog.models import Action
from posthog.models.cohort.cohort import Cohort
from posthog.temporal.ai.sync_entity_vectors import EntityConfig

from ee.hogai.summarizers.actions import ActionSummarizer
from ee.hogai.summarizers.chains import abatch_summarize_entity
from ee.hogai.summarizers.prompts import ACTIONS_SUMMARIZER_SYSTEM_PROMPT, COHORTS_SUMMARIZER_SYSTEM_PROMPT


class ActionEntityConfig(EntityConfig[Action]):
    @property
    def domain_name(self) -> str:
        return "action"

    @property
    def model_class(self) -> type[Action]:
        return Action

    def create_summarizer(self, entity: Action) -> ActionSummarizer:
        return ActionSummarizer(entity.team, entity)

    def get_queryset_filter(self, start_dt: datetime) -> Q:
        return Q(
            team__organization__is_ai_data_processing_approved=True,
            updated_at__lte=start_dt,
        ) & (
            Q(last_summarized_at__isnull=True, deleted=False)
            | Q(updated_at__gte=F("last_summarized_at"))
            | Q(last_summarized_at=start_dt)
        )

    def get_queryset_ordering(self) -> list[str]:
        return ["id", "team_id", "updated_at"]

    async def abatch_summarize(
        self, entities: list[Action], start_dt: str, properties: dict[str, Any]
    ) -> list[str | BaseException]:
        return await abatch_summarize_entity(
            entities=entities,
            summarizer_factory=self.create_summarizer,
            system_prompt=ACTIONS_SUMMARIZER_SYSTEM_PROMPT,
            domain=self.domain_name,
            entity_id_attr="id",
            start_dt=start_dt,
            properties=properties,
        )

    def get_sync_values_fields(self) -> list[str]:
        return ["team_id", "id", "summary", "name", "description", "deleted"]

    def build_clickhouse_properties(self, entity_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": entity_dict["name"],
            "description": entity_dict["description"],
        }


class CohortEntityConfig(EntityConfig[Cohort]):
    @property
    def domain_name(self) -> str:
        return "cohort"

    @property
    def model_class(self) -> type[Cohort]:
        return Cohort

    def get_queryset_filter(self, start_dt: datetime) -> Q:
        return Q(
            team__organization__is_ai_data_processing_approved=True,
            updated_at__lte=start_dt,
        ) & (
            Q(last_summarized_at__isnull=True, deleted=False)
            | Q(updated_at__gte=F("last_summarized_at"))
            | Q(last_summarized_at=start_dt)
        )

    def get_queryset_ordering(self) -> list[str]:
        return ["id", "team_id", "updated_at"]

    async def abatch_summarize(
        self, entities: list[Cohort], start_dt: str, properties: dict[str, Any]
    ) -> list[str | BaseException]:
        return await abatch_summarize_entity(
            entities=entities,
            summarizer_factory=self.create_summarizer,
            system_prompt=COHORTS_SUMMARIZER_SYSTEM_PROMPT,
            domain=self.domain_name,
            entity_id_attr="id",
            start_dt=start_dt,
            properties=properties,
        )

    def get_sync_values_fields(self) -> list[str]:
        return ["team_id", "id", "summary", "name", "description", "deleted", "is_static", "count"]

    def build_clickhouse_properties(self, entity_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": entity_dict["name"],
            "description": entity_dict["description"],
            "is_static": entity_dict["is_static"],
            "count": entity_dict["count"],
        }
