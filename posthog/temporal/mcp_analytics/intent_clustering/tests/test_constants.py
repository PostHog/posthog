from datetime import timedelta

from posthog.temporal.mcp_analytics.intent_clustering import constants

from products.mcp_analytics.backend import intent_clustering

# Reference costs behind the activity budget. Clustering was measured on 5,000
# synthetic 1536-d vectors (average linkage, cosine) at ~17s; it grows with n².
# Production workers can be slower than the laptop it was measured on.
CLUSTERING_SECONDS_AT_5000 = 17.0
SLOW_WORKER_FACTOR = 3.0
# Upper bound on one embedding-worker request on an uncached first run.
EMBEDDING_REQUEST_SECONDS = 0.5
# Upper bound on one chunked per-session ClickHouse query.
CORPUS_QUERY_SECONDS = 10.0


def _expected_compute_seconds(n_intents: int) -> float:
    clustering = CLUSTERING_SECONDS_AT_5000 * (n_intents / 5000) ** 2 * SLOW_WORKER_FACTOR
    embedding = n_intents / intent_clustering.EMBED_CONCURRENCY * EMBEDDING_REQUEST_SECONDS
    chunks = -(-intent_clustering.MAX_CORPUS_SESSIONS // intent_clustering.CORPUS_SESSION_CHUNK_SIZE)
    # Calls and advertised-tools queries each run once per chunk.
    queries = 2 * chunks * CORPUS_QUERY_SECONDS
    return clustering + embedding + queries


def test_workflow_cap_matches_pipeline_default() -> None:
    assert constants.DEFAULT_TOP_N_INTENTS == intent_clustering.DEFAULT_TOP_N_INTENTS


def test_compute_activity_timeout_covers_the_intent_cap() -> None:
    expected = _expected_compute_seconds(constants.DEFAULT_TOP_N_INTENTS)
    assert expected <= constants.COMPUTE_ACTIVITY_TIMEOUT.total_seconds()


def test_timeout_envelopes_nest() -> None:
    attempts = constants.COMPUTE_ACTIVITY_RETRY_POLICY.maximum_attempts
    assert constants.COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT >= attempts * constants.COMPUTE_ACTIVITY_TIMEOUT
    assert constants.WORKFLOW_EXECUTION_TIMEOUT >= constants.COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT + timedelta(minutes=1)


def test_a_chunk_of_session_calls_cannot_hit_the_row_cap() -> None:
    # A truncated chunk drops whole sessions by id order, silently shrinking the corpus.
    assert (
        intent_clustering.CORPUS_SESSION_CHUNK_SIZE * intent_clustering.MAX_CALLS_PER_SESSION
        <= intent_clustering.MAX_QUERY_ROWS
    )
