"""The evaluation template catalog. The frontend reads the same JSON files, so a template edit reaches both."""

import json
from functools import cache
from pathlib import Path
from typing import Any

from posthog.dataclasses import frozen

SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"


@frozen
class EvalTemplate:
    key: str
    name: str
    description: str
    category: str
    evaluation_type: str
    output_type: str
    output_config: dict[str, Any]
    target: str
    prompt: str | None
    source: str | None

    def evaluation_config(self) -> dict[str, Any]:
        if self.prompt is not None:
            return {"prompt": self.prompt}
        if self.source is not None:
            return {"source": self.source}
        return {}


@cache
def hog_examples() -> dict[str, str]:
    return {
        example["key"]: example["source"] for example in json.loads((SHARED_DIR / "hog_eval_examples.json").read_text())
    }


@cache
def templates() -> dict[str, EvalTemplate]:
    examples = hog_examples()
    catalog: dict[str, EvalTemplate] = {}
    for entry in json.loads((SHARED_DIR / "evaluation_templates.json").read_text()):
        source = examples[entry["hog_example"]] if "hog_example" in entry else entry.get("source")
        catalog[entry["key"]] = EvalTemplate(
            key=entry["key"],
            name=entry["name"],
            description=entry["description"],
            category=entry["category"],
            evaluation_type=entry["evaluation_type"],
            output_type=entry["output_type"],
            output_config=entry.get("output_config") or {},
            target=entry.get("target", "generation"),
            prompt=entry.get("prompt"),
            source=source,
        )
    return catalog


def template(key: str) -> EvalTemplate:
    return templates()[key]
