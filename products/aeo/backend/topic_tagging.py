"""The topic of a tracked question, picked by Jev from the topics the project already has.

Claude names a topic for each question it writes. A question that arrives without one, such as a CSV import,
gets the closest existing topic here, so the run's topic rotation and the topic reports see it.
"""

from __future__ import annotations

from collections.abc import Sequence

from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS

from products.aeo.backend import decisions

FEATURE = "topic_tagging"
MAX_TOPICS = GATEWAY_MAX_CHOICE_OPTIONS
# Below this the model is guessing between topics, and an empty topic is better than a wrong one.
KEEP_CONFIDENCE = 0.4

_QUESTION = "Which topic does the tracked question `{key}` belong to?"


def tag_topics(
    team_id: int,
    prompts: Sequence[str],
    topics: Sequence[str],
    *,
    site: str = "",
    usage: list[decisions.DecisionUsage] | None = None,
) -> list[str]:
    """A topic for each prompt, in the prompts' order, or "" where none fits well enough. At most
    `MAX_TOPICS` topics are offered: the first ones given. Raises `decisions.DecisionError` when the model
    gives no usable answer."""
    options = list(dict.fromkeys(topic for topic in topics if topic))[:MAX_TOPICS]
    if not prompts or not options:
        return [""] * len(prompts)
    choices = decisions.pick_one(
        team_id=team_id,
        feature=FEATURE,
        context={"site": site[:200] or "unknown"},
        items=list(prompts),
        item_key="questions",
        question=_QUESTION,
        options=dict.fromkeys(options),
        usage=usage,
    )
    return [choice.choice if choice is not None and choice.confidence >= KEEP_CONFIDENCE else "" for choice in choices]
