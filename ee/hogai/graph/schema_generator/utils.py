from typing import Generic, TypeVar

from pydantic import BaseModel

from posthog.schema import AssistantFunnelsQuery, AssistantHogQLQuery, AssistantRetentionQuery, AssistantTrendsQuery

Q = TypeVar("T", AssistantHogQLQuery, AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery)


class SchemaGeneratorOutput(BaseModel, Generic[Q]):
    query: Q
