import re
import unicodedata
from typing import Any

from posthog.hogql.escape_sql import escape_hogql_string

from products.ai_observability.backend.models.evaluation_configs import EvaluationType, OutputType
from products.ai_observability.backend.models.taggers import HogTaggerConfig, LLMTaggerConfig, TagDefinition

MAX_OPTION_KEY_LENGTH = 128

# The tagger runtime gave Hog code a `tags` list and dropped returned names that were not in it. The wrapper keeps
# that contract, and turns tag names into option keys, so the customer's code runs unchanged.
HOG_WRAPPER = """let tags := {tags}
fun tagger_result() {{
{source}
}}
let tag_keys := {tag_keys}
let returned := tagger_result()
if (typeof(returned) == 'string') {{
    returned := [returned]
}}
if (typeof(returned) != 'array') {{
    return []
}}
let categories := []
for (let tag in returned) {{
    let key := tag_keys[toString(tag)]
    if (key != null and not has(categories, key)) {{
        categories := arrayPushBack(categories, key)
    }}
}}
return categories
"""


def option_keys(tag_names: list[str]) -> list[str]:
    """A category key for each tag name, in the same order. Keys must be unique slugs, so a name with no letters or
    digits gets its position, and a repeated slug gets a number."""
    keys: list[str] = []
    for position, name in enumerate(tag_names, start=1):
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:MAX_OPTION_KEY_LENGTH].strip("_")
        base = slug or f"tag_{position}"
        key, suffix = base, 2
        while key in keys:
            ending = f"_{suffix}"
            key = f"{base[: MAX_OPTION_KEY_LENGTH - len(ending)].strip('_')}{ending}"
            suffix += 1
        keys.append(key)
    return keys


def _options(tags: list[TagDefinition]) -> list[dict[str, str]]:
    return [
        {"key": key, "label": tag.name} for key, tag in zip(option_keys([tag.name for tag in tags]), tags, strict=True)
    ]


def judge_prompt(config: LLMTaggerConfig) -> str:
    """The tagger prompt, plus what categories cannot hold: tag descriptions and limits other than "exactly one"."""
    parts = [config.prompt]
    described = [f"- {tag.name}: {tag.description}" for tag in config.tags if tag.description]
    if described:
        parts.append("What each category means:\n" + "\n".join(described))
    if config.max_tags != 1:
        limits = []
        if config.min_tags > 0:
            limits.append(f"at least {config.min_tags}")
        if config.max_tags is not None:
            limits.append(f"at most {config.max_tags}")
        if limits:
            parts.append(f"Select {' and '.join(limits)} categories.")
    elif config.min_tags == 0:
        parts.append("If no category applies, the criteria does not apply.")
    return "\n\n".join(parts)


def llm_judge_payload(config: LLMTaggerConfig) -> dict[str, Any]:
    single = config.max_tags == 1
    return {
        "evaluation_type": EvaluationType.LLM_JUDGE.value,
        # Taggers sent the judge text only, so attachments in generations stay out of the provider request.
        "evaluation_config": {"prompt": judge_prompt(config), "include_media": False},
        "output_type": OutputType.CATEGORICAL.value,
        "output_config": {
            "options": _options(config.tags),
            "selection_mode": "single" if single else "multiple",
            "allows_na": single and config.min_tags == 0,
        },
    }


def hog_source(config: HogTaggerConfig) -> str:
    names = [tag.name for tag in config.tags]
    tag_keys = ", ".join(
        f"{escape_hogql_string(name)}: {escape_hogql_string(key)}"
        for name, key in zip(names, option_keys(names), strict=True)
    )
    return HOG_WRAPPER.format(
        # The tagger runtime passed the tag names sorted, and code may index into the list.
        tags="[" + ", ".join(escape_hogql_string(name) for name in sorted(names)) + "]",
        source=config.source,
        tag_keys="{" + tag_keys + "}",
    )


def hog_payload(config: HogTaggerConfig) -> dict[str, Any]:
    return {
        "evaluation_type": EvaluationType.HOG.value,
        "evaluation_config": {"source": hog_source(config)},
        "output_type": OutputType.CATEGORICAL.value,
        "output_config": {"options": _options(config.tags), "selection_mode": "multiple", "allows_na": False},
    }


def conditions_payload(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tagger conditions without the bytecode the tagger compiled; the evaluation compiles its own."""
    return [
        {key: value for key, value in condition.items() if key not in ("bytecode", "bytecode_error")}
        for condition in conditions
    ]
