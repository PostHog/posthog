import uuid
from collections.abc import Sequence
from typing import Any

import structlog
import posthoganalytics
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompt_values import PromptValue
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from posthoganalytics.ai.langchain import CallbackHandler

from posthog.models import Action

from .actions import ActionSummarizer
from .prompts import ACTIONS_SUMMARIZER_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


async def abatch_summarize_actions(
    actions: Sequence[Action], start_dt: str | None = None, properties: dict[str, Any] | None = None
) -> list[str | BaseException]:
    trace_id = f"batch_actions_{start_dt}_{uuid.uuid4()}"
    props = properties or {}
    callback_handler = CallbackHandler(
        posthoganalytics.default_client,
        properties={
            **props,
            "batch_processing": True,
            "domain": "actions",
        },
        trace_id=trace_id,
    )

    prompts: list[PromptValue] = []
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

    chain = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1, streaming=False, max_retries=3) | StrOutputParser()
    return await chain.abatch(prompts, config={"callbacks": [callback_handler]}, return_exceptions=True)  # type: ignore  # typing doesn't match in LangChain
