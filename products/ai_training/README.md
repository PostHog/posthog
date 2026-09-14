# AI training

AI Research owns the deletion controls for ML training data.

The backend contains the privacy key store, encrypted-data reader, deletion requests, worker task, and management commands.
Feature tests and encryption fixtures live in `backend/tests/`.
Application lifecycle hooks call `backend/facade/api.py`.

The `AITrainingDeletionRequest` model uses the main PostgreSQL database so team deletion and its request commit together.
The worker keeps its existing Celery task name so queued tasks survive deployment.

Ingestion uses the organization's existing AI training opt-in flag.
Consent controls ingestion only; withdrawing consent preserves stored data and keys.
Re-enabling consent resumes existing sessions.
No consent backfill or deployment command is required.
Person deletion resolves sessions through the replay index and queues only session IDs.
ML data and key indexes do not store distinct IDs.
Replay index retention limits which sessions a person lookup can find.
The `delete_ai_training_month` command removes keys for a session month.

See [ML replay data contracts](docs/replay-data.md) for consent, encryption, deletion, and reader behavior.
