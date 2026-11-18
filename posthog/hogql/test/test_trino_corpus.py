from typing import cast

import pytest

from posthog.hogql.trino_corpus import (
    CorpusCaseResult,
    build_corpus_manifest,
    build_corpus_report,
    create_corpus_run_directory,
    write_generated_sql,
)


def test_manifest_tracks_all_fences_features_and_duplicates_without_sql() -> None:
    markdown = """# Queries

```sql
SELECT number FROM numbers(3)
```

```SQL title=duplicate
SELECT number FROM numbers(3)
```

```sql
SELECT value FROM events ARRAY JOIN properties.items AS value LIMIT 1 BY value
```
"""

    manifest = build_corpus_manifest(markdown)
    queries = cast(list[dict[str, object]], manifest["queries"])
    source = cast(dict[str, object], manifest["source"])

    assert isinstance(queries, list)
    assert [query["id"] for query in queries] == ["q0001", "q0002", "q0003"]
    assert queries[1]["duplicateOf"] == "q0001"
    assert queries[2]["features"] == ["array_join", "limit_by", "property_access"]
    assert source["sqlFenceCount"] == 3
    assert source["uniqueQueryCount"] == 2
    assert "sql" not in queries[0]


def test_manifest_ignores_feature_words_inside_literals_and_comments() -> None:
    manifest = build_corpus_manifest(
        """```sql
SELECT 'ARRAY JOIN', 1 -- LIMIT 2 BY key
/* numbers(3) */
```
"""
    )

    assert manifest["featureCounts"] == {}


def test_report_requires_one_terminal_result_for_every_manifest_query() -> None:
    manifest = build_corpus_manifest("""```sql
SELECT 1
```
""")

    with pytest.raises(ValueError, match="q0001"):
        build_corpus_report(manifest, {})

    result: CorpusCaseResult = {
        "category": "PASS_PARSE",
        "runtimeMs": 1.5,
        "featureCode": None,
        "generatedSqlSha256": "generated-hash",
        "generatedSqlBytes": 8,
    }
    report = build_corpus_report(manifest, {"q0001": result})
    report_queries = cast(list[dict[str, object]], report["queries"])

    assert report["categoryCounts"] == {"PASS_PARSE": 1}
    assert report_queries[0]["generatedSqlSha256"] == "generated-hash"


def test_report_rejects_results_for_unknown_queries() -> None:
    manifest = build_corpus_manifest("""```sql
SELECT 1
```
""")
    result: CorpusCaseResult = {
        "category": "PASS_PARSE",
        "runtimeMs": 1.5,
        "featureCode": None,
        "generatedSqlSha256": None,
        "generatedSqlBytes": None,
    }

    with pytest.raises(ValueError, match="q0002"):
        build_corpus_report(manifest, {"q0001": result, "q0002": result})


def test_each_corpus_run_uses_a_fresh_sql_directory(tmp_path) -> None:
    first_run = create_corpus_run_directory(tmp_path, "a" * 64)
    write_generated_sql(first_run, "q0001", "SELECT 1")
    second_run = create_corpus_run_directory(tmp_path, "a" * 64)

    assert first_run != second_run
    assert not list(second_run.glob("*.sql"))

    with pytest.raises(ValueError, match="Invalid corpus query identifier"):
        write_generated_sql(second_run, "../private", "SELECT 1")
