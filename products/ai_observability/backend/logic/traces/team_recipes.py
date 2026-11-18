import threading
from datetime import datetime
from typing import Final

from django.db.models import QuerySet

import structlog
from cachetools import LRUCache

from posthog.models import User

from ...models.parser_recipe import ParserRecipe
from ..message_normalizer.errors import RecipeTimeoutError
from ..message_normalizer.normalizer import RecipeNormalizer, StoredRecipe, compile_stored_recipe, merge_recipes
from ..message_normalizer.rules import Recipe
from ..message_normalizer.run_limits import check_time_limit

logger = structlog.get_logger(__name__)

COMPILED_RECIPE_CACHE_SIZE: Final = 256

type _RecipeVersion = tuple[str, datetime | None]

# A save moves `updated_at`, so an edited recipe gets a new key and is never served stale. A recipe that does not
# compile is cached as None, so it is not compiled again on every read.
_compiled_recipes: LRUCache[_RecipeVersion, Recipe | None] = LRUCache(maxsize=COMPILED_RECIPE_CACHE_SIZE)
# cachetools caches are not thread-safe, and the threads of one web worker share this cache.
_compiled_recipes_lock = threading.Lock()


def team_normalizer(team_id: int) -> RecipeNormalizer:
    return RecipeNormalizer(recipes=merge_recipes(_saved_recipes(team_id)))


def team_normalizer_with(team_id: int, candidate: Recipe) -> RecipeNormalizer:
    """The team's normalizer with a recipe not saved yet added where a newly saved one would run, after the rest."""
    return RecipeNormalizer(recipes=merge_recipes([*_saved_recipes(team_id), candidate]))


def save_team_recipe(team_id: int, user: User, *, name: str, source: str) -> str:
    return str(
        ParserRecipe.objects.for_team(team_id).create(team_id=team_id, created_by=user, name=name, source=source).id
    )


def _saved_recipes(team_id: int) -> list[Recipe]:
    team_recipes = ParserRecipe.objects.for_team(team_id)
    versions: list[_RecipeVersion] = [
        (str(recipe_id), updated_at)
        for recipe_id, updated_at in team_recipes.order_by("created_at", "id").values_list("id", "updated_at")
    ]
    with _compiled_recipes_lock:
        cached = {version: _compiled_recipes[version] for version in versions if version in _compiled_recipes}
    sources = _sources(team_recipes, [version for version in versions if version not in cached])
    recipes = [
        cached[version] if version in cached else _compiled_recipe(version, sources.get(version[0]))
        for version in versions
    ]
    return [recipe for recipe in recipes if recipe is not None]


def _sources(team_recipes: QuerySet[ParserRecipe], misses: list[_RecipeVersion]) -> dict[str, str]:
    # A source can be as long as the model allows, so only the recipes missing from the cache read theirs.
    if not misses:
        return {}
    rows = team_recipes.filter(id__in=[recipe_id for recipe_id, _ in misses]).values_list("id", "source")
    return {str(recipe_id): source for recipe_id, source in rows}


def _compiled_recipe(version: _RecipeVersion, source: str | None) -> Recipe | None:
    # A recipe deleted between the two reads has no source.
    if source is None:
        return None
    # The YAML parse cannot be interrupted, so the read's deadline is checked before it, and the compile after it
    # checks the deadline as it goes. A recipe skipped here leaves the cache untouched and compiles on a later read.
    try:
        check_time_limit()
        recipe = compile_stored_recipe(StoredRecipe(id=version[0], source=source))
    except RecipeTimeoutError:
        logger.warning("llma_team_recipe_skipped_at_deadline", recipe_id=version[0])
        return None
    with _compiled_recipes_lock:
        _compiled_recipes[version] = recipe
    return recipe
