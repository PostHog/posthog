from django.conf import settings

from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    SystemMessage as LangchainSystemMessage,
)
from langchain_core.output_parsers import StrOutputParser

from posthog.models import Team, User

from ee.hogai.llm import MaxChatOpenAI

INKEEP_DATA_CONTINUATION_PHRASE = "Now, let's get to your data request"

INKEEP_DOCS_SYSTEM_PROMPT = (
    "If the user has requested a query on analytics data (aka an insight) in their latest message, "
    f"""you MUST append "{INKEEP_DATA_CONTINUATION_PHRASE}: <brief query description>" to the end of your response."""
    "Do not reference any self-hosted related information in your response unless the user has explicitly asked about it."
)


async def search_documentation(query: str, *, user: User, team: Team) -> str:
    model = MaxChatOpenAI(
        model="inkeep-qa-expert",
        base_url="https://api.inkeep.com/v1/",
        api_key=settings.INKEEP_API_KEY,
        streaming=True,
        stream_usage=True,
        user=user,
        team=team,
    )
    chain = model | StrOutputParser()
    messages = [LangchainSystemMessage(content=INKEEP_DOCS_SYSTEM_PROMPT), LangchainHumanMessage(content=query)]
    response = await chain.ainvoke(messages)
    return response
