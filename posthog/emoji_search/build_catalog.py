"""Copy the pinned emojibase catalog used by frimousse into backend search data."""

import json
from pathlib import Path


def build_catalog() -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "frontend/node_modules/emojibase-data/en"
    data = json.loads((source / "data.json").read_text())
    messages = json.loads((source / "messages.json").read_text())
    version = json.loads((root / "frontend/node_modules/emojibase-data/package.json").read_text())["version"]

    groups = {group["order"]: group["message"] for group in messages["groups"]}
    subgroups: dict[int, list[str]] = {}
    for subgroup in messages["subgroups"]:
        subgroups.setdefault(subgroup["order"], []).append(subgroup["message"])

    emojis = [emoji for emoji in data if "group" in emoji]
    catalog = {
        "emojibase_version": version,
        "subgroups": [
            [group, subgroup, groups[group], ", ".join(subgroups[subgroup])]
            for group, subgroup in sorted({(emoji["group"], emoji["subgroup"]) for emoji in emojis})
        ],
        "emojis": [
            [emoji["emoji"], emoji["label"], emoji["group"], emoji["subgroup"], emoji.get("tags", [])]
            for emoji in emojis
        ],
    }
    destination = Path(__file__).with_name("catalog.json")
    destination.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    build_catalog()
