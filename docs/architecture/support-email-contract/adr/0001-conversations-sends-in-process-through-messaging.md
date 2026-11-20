# Conversations sends in-process through the Messaging facade

Django mail reaches Workflows over HTTP to `POSTHOG_HOST`, which is the US project from both regions. The Conversations outbox instead calls `send_code_email` from the Messaging facade in-process, from its own regional Celery worker. That way EU support replies always send from Frankfurt with no host setting. The call needs no project key or HTTP error mapping, and CDP applies the same idempotency on both paths. The cost is a Conversations to Messaging facade dependency.
