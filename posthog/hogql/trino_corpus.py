import re
import json
import hashlib
import argparse
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TypedDict

CorpusTerminalCategory = Literal[
    "PASS_PARSE",
    "PASS_ANALYZE",
    "PASS_EXECUTE",
    "FAIL_HOGQL_RESOLUTION",
    "FAIL_TRINO_LOWERING",
    "FAIL_TRINO_PRINTING",
    "FAIL_TRINO_SYNTAX",
    "FAIL_TABLE_NOT_FOUND",
    "FAIL_COLUMN_NOT_FOUND",
    "FAIL_TYPE_MISMATCH",
    "FAIL_UNSUPPORTED_SAFE_EQUIVALENT",
    "FAIL_EXECUTION",
    "FAIL_RESULT_MISMATCH",
]


class CorpusCaseResult(TypedDict):
    category: CorpusTerminalCategory
    runtimeMs: float
    featureCode: str | None
    generatedSqlSha256: str | None
    generatedSqlBytes: int | None


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


def create_corpus_run_directory(root: Path, source_sha256: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{source_sha256[:12]}-", dir=root))


def write_generated_sql(run_directory: Path, query_id: str, sql: str) -> Path:
    if not re.fullmatch(r"q[0-9]{4}", query_id):
        raise ValueError(f"Invalid corpus query identifier: {query_id}")
    output = run_directory / f"{query_id}.sql"
    output.write_text(sql)
    return output


def build_corpus_report(manifest: Mapping[str, object], results: Mapping[str, CorpusCaseResult]) -> dict[str, object]:
    manifest_queries = manifest.get("queries")
    if not isinstance(manifest_queries, list):
        raise ValueError("Corpus manifest must contain a query list")

    query_ids: list[str] = []
    reported_queries: list[dict[str, object]] = []
    category_counts: Counter[str] = Counter()
    for query in manifest_queries:
        if not isinstance(query, dict) or not isinstance(query.get("id"), str):
            raise ValueError("Corpus manifest contains a query without an identifier")
        query_id = query["id"]
        query_ids.append(query_id)
        result = results.get(query_id)
        if result is None:
            raise ValueError(f"Corpus query has no terminal result: {query_id}")
        category_counts[result["category"]] += 1
        reported_queries.append({**query, **result})

    unknown_ids = sorted(set(results).difference(query_ids))
    if unknown_ids:
        raise ValueError(f"Corpus results contain unknown query identifiers: {', '.join(unknown_ids)}")

    return {
        "categoryCounts": dict(sorted(category_counts.items())),
        "queries": reported_queries,
        "source": manifest.get("source"),
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
