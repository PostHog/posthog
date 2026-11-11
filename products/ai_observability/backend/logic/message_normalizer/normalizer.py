import functools
import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import structlog

from posthog.dataclasses import frozen

from .compiler import compile_recipe
from .errors import RecipeCompileError, RecipeRuntimeError
from .pipeline import TIME_LIMIT_SECONDS, RecipePipeline, RunOutcome
from .roles import AVAILABLE_TOOLS_ROLE
from .rules import Recipe
from .run_limits import run_limits
from .values import MISSING, CompatMessage, JsonValue, Missing, Value, is_object_like, is_truthy, to_json_value
from .yaml_loader import load_recipe_yaml

logger = structlog.get_logger(__name__)

DEFAULT_RECIPES_DIR: Final = Path(__file__).parent / "default_recipes"

# The first matching rule wins, so this order is load-bearing. It matches the TypeScript registry.
DEFAULT_RECIPE_FILES: Final = (
    "dispatcher_entry",
    "compat_array",
    "litellm",
    "langchain_envelope",
    "langchain",
    "vercel_sdk",
    "openai_chat",
    "openai_responses",
    "typed_agent_items",
    "anthropic",
    "otel",
    "wrappers",
)


@frozen
class StoredRecipe:
    id: str
    source: str


@functools.cache
def default_recipes() -> tuple[Recipe, ...]:
    recipes = tuple(
        compile_recipe(load_recipe_yaml((DEFAULT_RECIPES_DIR / f"{name}.yaml").read_text(encoding="utf-8")))
        for name in DEFAULT_RECIPE_FILES
    )
    ids = [recipe.id for recipe in recipes]
    if len(set(ids)) != len(ids):
        raise RecipeCompileError(f"Duplicate bundled recipe ids: {sorted(ids)}")
    return recipes


def merge_recipes(customs: Sequence[Recipe]) -> list[Recipe]:
    # Team recipes run after every built-in, so they catch inputs the built-ins miss without ever shadowing them.
    return [*default_recipes(), *customs]


def compile_stored_recipe(stored: StoredRecipe) -> Recipe | None:
    # A team recipe that does not compile is skipped, so a bad edit can never break trace rendering.
    try:
        recipe = _compile_stored_source(stored)
    except RecipeCompileError as error:
        logger.warning(
            "llma_team_recipe_skipped", recipe_id=stored.id, error_type=type(error.__cause__ or error).__name__
        )
        return None
    return recipe


def check_stored_recipe_source(source: str) -> None:
    """Raises `RecipeCompileError` when `compile_stored_recipe` would skip this source."""
    # A recipe being saved for the first time has no database id yet, and a stored recipe needs no `id:` of its own.
    _compile_stored_source(StoredRecipe(id="unsaved", source=source))


def _compile_stored_source(stored: StoredRecipe) -> Recipe:
    return dataclasses.replace(compile_recipe(load_recipe_yaml(stored.source), stored.id), id=stored.id)


class RecipeNormalizer:
    def __init__(self, recipes: Sequence[Recipe] | None = None, time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        self._pipeline = RecipePipeline(default_recipes() if recipes is None else recipes, time_limit_seconds)

    def normalize_message(self, value: Value, default_role: str) -> RunOutcome:
        if isinstance(value, Missing):
            return RunOutcome(messages=(), recognized=True)
        return self._pipeline.run(value, default_role)

    def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
        # The run inside joins these limits, so copying the tools and normalizing the messages share one budget and
        # one deadline.
        with run_limits(self._pipeline.time_limit_seconds):
            # `tools` is a function parameter, not a message shape, so no recipe covers it.
            tools_messages: tuple[CompatMessage, ...] = (
                ({"role": AVAILABLE_TOOLS_ROLE, "content": "", "tools": _tools_value(tools)},)
                if is_truthy(tools)
                else ()
            )
            if isinstance(value, str) or is_object_like(value):
                outcome = self.normalize_message(value, default_role)
                return RunOutcome(messages=(*tools_messages, *outcome.messages), recognized=outcome.recognized)
            return RunOutcome(messages=tools_messages, recognized=True)


def _tools_value(tools: Value) -> JsonValue:
    try:
        return to_json_value(tools)
    except RecursionError as error:
        raise RecipeRuntimeError("RecipeNormalizer: the tools nest too deeply to normalize") from error
