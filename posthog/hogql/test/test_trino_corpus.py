from posthog.hogql.trino_corpus import build_corpus_manifest


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
    queries = manifest["queries"]

    assert isinstance(queries, list)
    assert [query["id"] for query in queries] == ["q0001", "q0002", "q0003"]
    assert queries[1]["duplicateOf"] == "q0001"
    assert queries[2]["features"] == ["array_join", "limit_by", "property_access"]
    assert manifest["source"]["sqlFenceCount"] == 3
    assert manifest["source"]["uniqueQueryCount"] == 2
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
