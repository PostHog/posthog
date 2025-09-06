"""
This module contains types that are composed from the different graphs.
This is used to avoid circular imports.
"""

from typing import Union

from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

# Define the types using actual classes
MaxNodeName = Union[AssistantNodeName, TaxonomyNodeName, DeepResearchNodeName]

MaxGraphState = Union[AssistantState, TaxonomyAgentState, DeepResearchState]

MaxPartialGraphState = Union[PartialAssistantState, TaxonomyAgentState, PartialDeepResearchState]

# States that are used in the Assistant class
AssistantMaxGraphState = Union[AssistantState, DeepResearchState]
AssistantMaxPartialGraphState = Union[PartialAssistantState, PartialDeepResearchState]
