import json
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.core.cache import cache

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import build_system_one_client

MODEL = "posthog/hogference/jevk5-fp8-0.2"
CACHE_SECONDS = 24 * 60 * 60
OPTIONS_PER_QUESTION = 15


@dataclass(frozen=True)
class EmojiSuggestion:
    emoji: str
    label: str


@dataclass(frozen=True)
class CatalogEmoji:
    suggestion: EmojiSuggestion
    subgroup: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CatalogSubgroup:
    label: str
    emoji_keys: tuple[str, ...]


@dataclass(frozen=True)
class EmojiCatalog:
    emojis: dict[str, CatalogEmoji]
    subgroups: dict[str, CatalogSubgroup]


@lru_cache(maxsize=1)
def load_catalog() -> EmojiCatalog:
    source = Path(__file__).with_name("catalog.json")
    raw = json.loads(source.read_text())
    labels = {
        f"{group}-{subgroup}": f"{group_label} / {subgroup_label}"
        for group, subgroup, group_label, subgroup_label in raw["subgroups"]
    }
    emojis = {
        f"e{index}": CatalogEmoji(EmojiSuggestion(emoji, label), f"{group}-{subgroup}", tuple(tags))
        for index, (emoji, label, group, subgroup, tags) in enumerate(raw["emojis"])
    }
    subgroups = {
        subgroup: CatalogSubgroup(label, tuple(key for key, emoji in emojis.items() if emoji.subgroup == subgroup))
        for subgroup, label in labels.items()
    }
    return EmojiCatalog(emojis, subgroups)


def _chunks(items: list[str] | tuple[str, ...]) -> list[list[str]]:
    return [list(items[index : index + OPTIONS_PER_QUESTION]) for index in range(0, len(items), OPTIONS_PER_QUESTION)]


def build_subgroup_questions(catalog: EmojiCatalog) -> dict[str, ChoiceQuestion]:
    questions: dict[str, ChoiceQuestion] = {}
    for index, subgroup_ids in enumerate(_chunks(list(catalog.subgroups))):
        criteria = {}
        for subgroup_id in subgroup_ids:
            subgroup = catalog.subgroups[subgroup_id]
            names = [catalog.emojis[key].suggestion.label for key in subgroup.emoji_keys]
            examples = names if len(names) <= 8 else names[:4] + names[-4:]
            criteria[f"s{subgroup_id}"] = f"{subgroup.label}: {', '.join(examples)}"
        criteria["none"] = "None of these emoji groups fit the search"
        questions[f"subgroup{index}"] = ChoiceQuestion(
            instructions="Which emoji groups are relevant to the search?", criteria=criteria
        )
    return questions


def build_emoji_questions(catalog: EmojiCatalog, subgroup_ids: list[str]) -> dict[str, ChoiceQuestion]:
    questions: dict[str, ChoiceQuestion] = {}
    for subgroup_id in subgroup_ids:
        for keys in _chunks(catalog.subgroups[subgroup_id].emoji_keys):
            criteria = {
                key: f"{catalog.emojis[key].suggestion.emoji} {catalog.emojis[key].suggestion.label}; {', '.join(catalog.emojis[key].tags[:8])}"
                for key in keys
            }
            criteria["none"] = "No emoji in this set fits the search"
            questions[f"emoji{len(questions)}"] = ChoiceQuestion(
                instructions="Which emojis are relevant to the search?", criteria=criteria
            )
    return questions


def _ranked_probabilities(answers, valid_keys: set[str]) -> dict[str, float]:
    scores = {}
    for answer in answers.values():
        if isinstance(answer, ChoiceAnswer):
            none_probability = answer.probabilities["none"]
            scores.update(
                {
                    key: probability
                    for key, probability in answer.probabilities.items()
                    if key in valid_keys and probability > none_probability and probability >= 0.1
                }
            )
    return scores


def suggest_emojis(query: str, *, team_id: int) -> list[EmojiSuggestion]:
    query = " ".join(query.split())
    if not 3 <= len(query) <= 64:
        return []

    catalog = load_catalog()
    cache_key = f"emoji_search:v2:{team_id}:{hashlib.sha256(query.lower().encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        try:
            keys = json.loads(cached)
            if isinstance(keys, list) and all(isinstance(key, str) and key in catalog.emojis for key in keys):
                return [catalog.emojis[key].suggestion for key in keys]
        except (TypeError, ValueError):
            pass

    client = build_system_one_client(
        model=MODEL, ai_product="emoji_search", distinct_id=team_distinct_id(team_id), timeout=1.2
    )
    state = {"emoji_search": query}
    subgroup_result = client.decide(state=state, questions=build_subgroup_questions(catalog))
    subgroup_scores = _ranked_probabilities(
        subgroup_result.answers, {f"s{subgroup_id}" for subgroup_id in catalog.subgroups}
    )
    subgroup_ids = [key[1:] for key in sorted(subgroup_scores, key=lambda key: -subgroup_scores[key])[:3]]
    if not subgroup_ids:
        cache.set(cache_key, "[]", CACHE_SECONDS)
        return []

    emoji_result = client.decide(state=state, questions=build_emoji_questions(catalog, subgroup_ids))
    emoji_scores = _ranked_probabilities(emoji_result.answers, set(catalog.emojis))
    keys = sorted(
        emoji_scores,
        key=lambda key: -emoji_scores[key] * subgroup_scores[f"s{catalog.emojis[key].subgroup}"],
    )[:4]
    cache.set(cache_key, json.dumps(keys), CACHE_SECONDS)
    return [catalog.emojis[key].suggestion for key in keys]
