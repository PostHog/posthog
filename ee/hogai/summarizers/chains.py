from collections.abc import Sequence

import posthoganalytics
import structlog
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from posthog.models import Action

from .actions import ActionSummarizer
from .prompts import ACTIONS_SUMMARIZER_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


async def abatch_summarize_actions(actions: Sequence[Action]) -> list[str | BaseException]:
    prompts = []
    for action in actions:
        try:
            action_summarizer = ActionSummarizer(action)
        except Exception as e:
            posthoganalytics.capture_exception(e, properties={"action_id": action.id, "tag": "max_ai"})
            logger.exception("Error summarizing actions", error=e, action_id=action.id)
            continue

        taxonomy_prompt = action_summarizer.taxonomy_description
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ACTIONS_SUMMARIZER_SYSTEM_PROMPT),
                ("user", "{action_description}"),
            ]
        ).format_prompt(
            taxonomy=f"\n\n{taxonomy_prompt}" if taxonomy_prompt else "",
            action_description=action_summarizer.summary,
        )
        prompts.append(prompt)

    chain = ChatOpenAI(model="gpt-4o", temperature=0, streaming=False) | StrOutputParser()
    return await chain.abatch(prompts, return_exceptions=True)
