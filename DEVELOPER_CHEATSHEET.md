# Quick reference to common development tasks

## ClickHouse debugging

### How do I see which queries are sent to ClickHouse

In tests, run:

```
pytest <path-to-test> --log-cli-level=DEBUG
```

This should dump all debug log messages (not just ClickHouse) to stdout

In dev or production, you can run, for example:

```
echo "select query from system.query_log limit 10" | clickhouse-client
```
