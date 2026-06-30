# Retries, throttling, and non-retryable errors

## Retry and throttling strategy

- Use `tenacity` instead of manual retry loops.
- Retry transport failures and retryable status codes (`429`, transient `5xx`).
- Prefer server-provided rate-limit reset headers on `429`; fall back to exponential backoff.
- Bound and make deterministic (`stop_after_attempt`). Preserve clear terminal behavior.
- Keep timeout/retry settings near the top of the module for easy tuning.

## Non-retryable errors

Override `get_non_retryable_errors()` to mark errors that should permanently fail instead of retrying:

```python
def get_non_retryable_errors(self) -> dict[str, str | None]:
    return {
        "401 Client Error: Unauthorized for url: https://api.example.com": "Your API key is invalid or expired. Please generate a new key and reconnect.",
        "403 Client Error: Forbidden for url: https://api.example.com": "Your API key does not have the required permissions. Please check the key permissions and try again.",
    }
```

Common cases: 401 Unauthorized, 403 Forbidden, invalid/expired tokens, OAuth tokens needing re-auth.
