# Support send idempotency outlives the outbox's retry age

The outbox retries a pending reply for up to 5 days so it can survive a long outage. The public code-send API only promises a 24-hour replay window. Without a longer window, a retry after a lost response could send the reply twice. Workflows therefore keeps idempotency records for `stream=SUPPORT` sends longer than the outbox's maximum age. Shortening the outbox age was rejected because it gives up outage tolerance.
