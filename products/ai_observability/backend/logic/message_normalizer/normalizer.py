import functools
import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from posthog.dataclasses import frozen

from .compiler import compile_recipe
from .errors import RecipeCompileError, RecipeRuntimeError
from .pipeline import TIME_LIMIT_SECONDS, RecipePipeline, RunOutcome
from .roles import AVAILABLE_TOOLS_ROLE
from .rules import Recipe
from .values import MISSING, CompatMessage, JsonValue, Missing, Value, is_object_like, is_truthy, to_json_value
from .yaml_loader import load_recipe_yaml

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


def merge_recipes(stored: Sequence[StoredRecipe]) -> list[Recipe]:
    # Team recipes run after every built-in, so they catch inputs the built-ins miss without ever shadowing them.
    customs = [recipe for recipe in map(_compile_stored, stored) if recipe is not None]
    return [*default_recipes(), *customs]


def _compile_stored(stored: StoredRecipe) -> Recipe | None:
    # A team recipe that does not compile is skipped, so a bad edit can never break trace rendering.
    try:
        recipe = compile_recipe(load_recipe_yaml(stored.source), stored.id)
    except RecipeCompileError:
        return None
    return dataclasses.replace(recipe, id=stored.id)


class RecipeNormalizer:
    # The pipeline keeps a per-run budget, so one instance must not serve two runs at once.
    def __init__(self, recipes: Sequence[Recipe] | None = None, time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        self._pipeline = RecipePipeline(default_recipes() if recipes is None else recipes, time_limit_seconds)

    def normalize_message(self, value: Value, default_role: str) -> RunOutcome:
        if isinstance(value, Missing):
            return RunOutcome(messages=[], recognized=True)
        return self._pipeline.run(value, default_role)

    def normalize_messages(self, value: Value, default_role: str, tools: Value = MISSING) -> RunOutcome:
        messages: list[CompatMessage] = []
        if is_truthy(tools):
            # `tools` is a function parameter, not a message shape, so no recipe covers it.
            messages.append({"role": AVAILABLE_TOOLS_ROLE, "content": "", "tools": _tools_value(tools)})
        if isinstance(value, str) or is_object_like(value):
            outcome = self.normalize_message(value, default_role)
            return RunOutcome(messages=[*messages, *outcome.messages], recognized=outcome.recognized)
        return RunOutcome(messages=messages, recognized=True)


def _tools_value(tools: Value) -> JsonValue:
    try:
        return to_json_value(tools)
    except RecursionError as error:
        raise RecipeRuntimeError("RecipeNormalizer: the tools nest too deeply to normalize") from error
