from collections.abc import Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from posthog.models import Action

from .actions import ActionSummarizer
from .prompts import ACTIONS_SUMMARIZER_SYSTEM_PROMPT


def batch_summarize_actions(actions: Sequence[Action]) -> list[str | BaseException]:
    prompts = []
    for action in actions:
        action_summarizer = ActionSummarizer(action)
        taxonomy_prompt = action_summarizer.taxonomy_description
        prompt = ChatPromptTemplate.from_messages(
            ("system", ACTIONS_SUMMARIZER_SYSTEM_PROMPT),
            ("user", "{action_description}"),
        ).format_prompt(
            {
                "taxonomy": f"\n\n{taxonomy_prompt}" if taxonomy_prompt else "",
                "action_description": action_summarizer.summary,
            }
        )
        prompts.append(prompt)

    chain = ChatOpenAI(model="gpt-4o", temperature=0, streaming=False) | StrOutputParser()
    return chain.batch(prompts, return_exceptions=True)
