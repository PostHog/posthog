# AI training

AI Research owns the consent and deletion controls for ML training data.

The backend contains the privacy key store, encrypted-data reader, consent state, deletion requests, worker task, and management commands.
Feature tests and encryption fixtures live in `backend/tests/`.
Application lifecycle hooks call `backend/facade/api.py`.

The models use the main PostgreSQL database to keep consent updates and team deletion requests in their application transactions.
Their table names remain `posthog_aitrainingconsent` and `posthog_aitrainingprivacyrequest`.
The worker keeps its existing Celery task name so queued tasks survive deployment.

Organizations without v2 consent state use their existing AI training opt-in.
No consent backfill or deployment command is required.
The `delete_ai_training_month` command removes keys for a session month.

See [ML replay data contracts](docs/replay-data.md) for consent, encryption, deletion, and reader behavior.
