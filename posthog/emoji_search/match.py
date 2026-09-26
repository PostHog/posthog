import json
import hashlib
from dataclasses import dataclass

from django.core.cache import cache

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import build_system_one_client

MODEL = "posthog/hogference/jevk5-fp8-0.2"
CACHE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class EmojiSuggestion:
    emoji: str
    label: str


THEMES: dict[str, tuple[str, tuple[EmojiSuggestion, ...]]] = {
    "dinosaurs": (
        "Prehistoric animals, dinosaurs, Jurassic stories",
        (EmojiSuggestion("🦖", "T-Rex"), EmojiSuggestion("🦕", "sauropod")),
    ),
    "theme parks": (
        "Amusement parks, rides, fairs",
        (EmojiSuggestion("🎢", "roller coaster"), EmojiSuggestion("🎡", "ferris wheel")),
    ),
    "films": (
        "Films, cinema, watching movies",
        (EmojiSuggestion("🎬", "clapper board"), EmojiSuggestion("🍿", "popcorn")),
    ),
    "space": ("Space, stars, astronomy", (EmojiSuggestion("🚀", "rocket"), EmojiSuggestion("🌌", "milky way"))),
    "sea": ("Oceans, beaches, sea animals", (EmojiSuggestion("🌊", "water wave"), EmojiSuggestion("🐬", "dolphin"))),
    "weather": (
        "Weather, sunshine, storms",
        (EmojiSuggestion("☀️", "sun"), EmojiSuggestion("⛈️", "cloud with lightning and rain")),
    ),
    "plants": (
        "Trees, flowers, forests, gardens",
        (EmojiSuggestion("🌳", "deciduous tree"), EmojiSuggestion("🌷", "tulip")),
    ),
    "celebrations": (
        "Parties, birthdays, congratulations",
        (EmojiSuggestion("🎉", "party popper"), EmojiSuggestion("🎂", "birthday cake")),
    ),
    "love": ("Love, romance, affection", (EmojiSuggestion("❤️", "red heart"), EmojiSuggestion("💕", "two hearts"))),
    "technology": ("Computers, robots, programming", (EmojiSuggestion("💻", "laptop"), EmojiSuggestion("🤖", "robot"))),
    "food": ("Eating, meals, restaurants", (EmojiSuggestion("🍕", "pizza"), EmojiSuggestion("🍔", "hamburger"))),
    "travel": ("Trips, flying, holidays", (EmojiSuggestion("✈️", "airplane"), EmojiSuggestion("🧳", "luggage"))),
    "sports": ("Games, competition, winning", (EmojiSuggestion("⚽", "soccer ball"), EmojiSuggestion("🏆", "trophy"))),
    "music": ("Songs, concerts, instruments", (EmojiSuggestion("🎵", "musical note"), EmojiSuggestion("🎸", "guitar"))),
    "fantasy": ("Magic, fairy tales, mystery", (EmojiSuggestion("🔮", "crystal ball"), EmojiSuggestion("🧙", "mage"))),
}


def suggest_emojis(query: str, *, team_id: int) -> list[EmojiSuggestion]:
    query = " ".join(query.split())
    if not 3 <= len(query) <= 64:
        return []

    cache_key = f"emoji_search:v1:{team_id}:{hashlib.sha256(query.lower().encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        try:
            names = json.loads(cached)
            if isinstance(names, list) and all(isinstance(name, str) and name in THEMES for name in names):
                return [emoji for name in names for emoji in THEMES[name][1]]
        except (TypeError, ValueError):
            pass

    client = build_system_one_client(
        model=MODEL, ai_product="emoji_search", distinct_id=team_distinct_id(team_id), timeout=0.8
    )
    criteria = {name: description for name, (description, _) in THEMES.items()}
    criteria["none"] = "None of these topics fit the search"
    result = client.decide(
        state=f"Emoji search: {query}",
        questions={"theme": ChoiceQuestion(instructions="Which topics fit this emoji search?", criteria=criteria)},
    )
    answer = result.answers["theme"]
    if not isinstance(answer, ChoiceAnswer):
        return []
    none_probability = answer.probabilities["none"]
    names = [
        name
        for name, probability in sorted(answer.probabilities.items(), key=lambda pair: -pair[1])
        if name in THEMES and probability > none_probability and probability >= 0.1
    ][:2]
    cache.set(cache_key, json.dumps(names), CACHE_SECONDS)
    return [emoji for name in names for emoji in THEMES[name][1]]
