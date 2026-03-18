from typing import Generic, TypeVar

from pydantic import BaseModel

from posthog.schema import AssistantFunnelsQuery, AssistantHogQLQuery, AssistantRetentionQuery, AssistantTrendsQuery

Q = TypeVar("Q", AssistantHogQLQuery, AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery)


class SchemaGeneratorOutput(BaseModel, Generic[Q]):
    query: Q
