"""
This module contains types that are composed from the different graphs.
This is used to avoid circular imports.
"""

from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.research_agent.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

MaxNodeName = AssistantNodeName | TaxonomyNodeName | DeepResearchNodeName

MaxGraphState = AssistantState | TaxonomyAgentState | DeepResearchState

MaxPartialGraphState = PartialAssistantState | TaxonomyAgentState | PartialDeepResearchState

# States that are used in the Assistant class
AssistantMaxGraphState = AssistantState | DeepResearchState
AssistantMaxPartialGraphState = PartialAssistantState | PartialDeepResearchState
