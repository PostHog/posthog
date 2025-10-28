import uuid
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import structlog
import posthoganalytics
from asgiref.sync import sync_to_async
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompt_values import PromptValue
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from posthoganalytics.ai.langchain import CallbackHandler

from ee.hogai.summarizers.utils import Summarizer

T = TypeVar("T")

logger = structlog.get_logger(__name__)


async def abatch_summarize_entity(
    entities: Sequence[T],
    summarizer_factory: Callable[[T], Summarizer],
    system_prompt: str,
    domain: str,
    entity_id_attr: str = "id",
    start_dt: str | None = None,
    properties: dict[str, Any] | None = None,
) -> list[str | BaseException]:
    """
    Generic function to summarize entities using LLM.
    Args:
        entities: Sequence of entities to summarize
        summarizer_factory: Function that creates a summarizer for an entity
        system_prompt: System prompt for the LLM
        domain: Domain name for analytics tracking
        entity_id_attr: Attribute name to get entity ID for error tracking
        start_dt: Start date for trace ID
        properties: Additional properties for analytics
    """
    trace_id = f"batch_{domain}_{start_dt}_{uuid.uuid4()}"
    props = properties or {}
    callback_handler = CallbackHandler(
        posthoganalytics.default_client,
        properties={
            **props,
            "batch_processing": True,
            "domain": domain,
        },
        trace_id=trace_id,
    )

    prompts: list[PromptValue] = []
    for entity in entities:
        try:
            summarizer = await sync_to_async(summarizer_factory)(entity)
        except Exception as e:
            entity_id = getattr(entity, entity_id_attr, "unknown")
            posthoganalytics.capture_exception(e, properties={f"{domain}_id": entity_id, "tag": "max_ai"})
            logger.exception(f"Error summarizing {domain}", error=e, **{f"{domain}_id": entity_id})
            continue

        # Get the summary and any additional context (like taxonomy)
        summary = await sync_to_async(lambda s=summarizer: s.summary)()
        taxonomy_prompt = ""
        if hasattr(summarizer, "taxonomy_description"):
            taxonomy_prompt = await sync_to_async(lambda s=summarizer: s.taxonomy_description)()

        prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("user", "{entity_description}"),
            ]
        )

        # Prepare parameters based on what the template needs
        format_params = {"entity_description": summary}

        format_params["taxonomy"] = f"\n\n{taxonomy_prompt}" if taxonomy_prompt else ""

        prompt = prompt_template.format_prompt(**format_params)
        logger.info(prompt.to_string())
        prompts.append(prompt)

    chain = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1, streaming=False, max_retries=3) | StrOutputParser()
    return await chain.abatch(prompts, config={"callbacks": [callback_handler]}, return_exceptions=True)  # type: ignore  # typing doesn't match in LangChain
