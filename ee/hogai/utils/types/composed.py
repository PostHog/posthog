"""
This module contains types that are composed from the different graphs.
This is used to avoid circular imports.
"""

from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState, TaxonomyNodeName
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

MaxNodeName = AssistantNodeName | TaxonomyNodeName

MaxGraphState = AssistantState | TaxonomyAgentState

MaxPartialGraphState = PartialAssistantState | TaxonomyAgentState

# States that are used in the Assistant class
AssistantMaxGraphState = AssistantState | TaxonomyAgentState
AssistantMaxPartialGraphState = PartialAssistantState | TaxonomyAgentState
