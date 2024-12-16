from langchain_core.prompts import ChatPromptTemplate

from ee.hogai.memory.prompts import INITIALIZE_CORE_MEMORY_PROMPT


def initialize_memory():
    _ = ChatPromptTemplate.from_messages([("human", INITIALIZE_CORE_MEMORY_PROMPT)])
