# Agent-server shadow observer

This Go process polls the agent-server health endpoint and emits one JSON record
when the session is ready or the request times out.

```bash
go run . --boot-id "$POSTHOG_TASK_RUN_ID" --health-url http://127.0.0.1:8080/health
```

The observer is read-only. It does not accept traffic, start sessions, change
repositories, call models, or clean up processes.
