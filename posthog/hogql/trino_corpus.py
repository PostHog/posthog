import re
import json
import hashlib
import argparse
from collections import Counter
from pathlib import Path

_SQL_FENCE = re.compile(r"^```sql[^\n]*\n(.*?)^```[ \t]*$", re.IGNORECASE | re.MULTILINE | re.DOTALL)
_FEATURE_PATTERNS = {
    "any_join": re.compile(r"\b(?:LEFT\s+)?ANY\s+(?:INNER\s+)?JOIN\b", re.IGNORECASE),
    "array_join": re.compile(r"\b(?:LEFT\s+|INNER\s+)?ARRAY\s+JOIN\b", re.IGNORECASE),
    "lambda": re.compile(r"->"),
    "limit_by": re.compile(r"\bLIMIT\s+.+?\s+BY\b", re.IGNORECASE | re.DOTALL),
    "numbers": re.compile(r"\bnumbers\s*\(", re.IGNORECASE),
    "prewhere": re.compile(r"\bPREWHERE\b", re.IGNORECASE),
    "property_access": re.compile(r"\bproperties\s*(?:\.|\[)", re.IGNORECASE),
    "qualify": re.compile(r"\bQUALIFY\b", re.IGNORECASE),
    "window": re.compile(r"\bOVER\s*\(", re.IGNORECASE),
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sanitize_sql(sql: str) -> str:
    output: list[str] = []
    index = 0
    state = "normal"
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "normal":
            if char == "'":
                state = "single"
                output.append(" ")
            elif char == "-" and next_char == "-":
                state = "line_comment"
                output.extend((" ", " "))
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                output.extend((" ", " "))
                index += 1
            else:
                output.append(char)
        elif state == "single":
            if char == "'" and next_char == "'":
                output.extend((" ", " "))
                index += 1
            elif char == "'":
                state = "normal"
                output.append(" ")
            else:
                output.append("\n" if char == "\n" else " ")
        elif state == "line_comment":
            if char == "\n":
                state = "normal"
                output.append("\n")
            else:
                output.append(" ")
        elif char == "*" and next_char == "/":
            state = "normal"
            output.extend((" ", " "))
            index += 1
        else:
            output.append("\n" if char == "\n" else " ")
        index += 1
    return "".join(output)


def build_corpus_manifest(markdown: str) -> dict[str, object]:
    queries: list[dict[str, object]] = []
    first_id_by_hash: dict[str, str] = {}
    feature_counts: Counter[str] = Counter()
    for index, block in enumerate(_SQL_FENCE.findall(markdown), start=1):
        query_id = f"q{index:04d}"
        sql = block.rstrip() + "\n"
        digest = _sha256(sql)
        sanitized = _sanitize_sql(sql)
        features = sorted(name for name, pattern in _FEATURE_PATTERNS.items() if pattern.search(sanitized))
        feature_counts.update(features)
        record: dict[str, object] = {
            "bytes": len(sql.encode()),
            "characters": len(sql),
            "features": features,
            "id": query_id,
            "lines": len(sql.splitlines()),
            "sha256": digest,
        }
        duplicate_of = first_id_by_hash.get(digest)
        if duplicate_of is None:
            first_id_by_hash[digest] = query_id
        else:
            record["duplicateOf"] = duplicate_of
        queries.append(record)

    return {
        "featureCounts": dict(sorted(feature_counts.items())),
        "queries": queries,
        "source": {
            "bytes": len(markdown.encode()),
            "characters": len(markdown),
            "sha256": _sha256(markdown),
            "sqlFenceCount": len(queries),
            "uniqueQueryCount": len(first_id_by_hash),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_corpus_manifest(args.source.read_text())
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
