import json
import tiktoken
import datetime
import pytz

from typing import Any, Optional

from abc import ABC, abstractmethod
from prometheus_client import Histogram, Counter
from structlog import get_logger
from openai import OpenAI

from posthog.models import Team
from posthog.clickhouse.client import sync_execute

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from ee.session_recordings.ai.utils import (
    SessionSummaryPromptData,
    simplify_window_id,
    format_dates,
    collapse_sequence_of_events,
    only_pageview_urls,
)

_encoding: Optional[tiktoken.Encoding] = None


def get_encoding() -> tiktoken.Encoding:
    global _encoding
    if not _encoding:
        # NOTE: This does an API request so we want to ensure we load it lazily and not at startup
        # tiktoken.encoding_for_model(model_name) specifies encoder
        # model_name = "text-embedding-3-small" for this usecase
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


MAX_TOKENS_FOR_MODEL = 8191

RECORDING_EMBEDDING_TOKEN_COUNT = Histogram(
    "posthog_session_recordings_recording_embedding_token_count",
    "Token count for individual recordings generated during embedding",
    buckets=[0, 100, 500, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
    labelnames=["source_type"],
)

GENERATE_RECORDING_EMBEDDING_TIMING = Histogram(
    "posthog_session_recordings_generate_recording_embedding",
    "Time spent generating recording embeddings for a single session",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20],
    labelnames=["source_type"],
)

SESSION_EMBEDDINGS_GENERATED = Counter(
    "posthog_session_recordings_embeddings_generated",
    "Number of session embeddings generated",
    labelnames=["source_type"],
)

SESSION_EMBEDDINGS_FAILED = Counter(
    "posthog_session_recordings_embeddings_failed",
    "Instance of an embedding request to open AI (and its surrounding work) failing and being swallowed",
    labelnames=["source_type"],
)

SESSION_EMBEDDINGS_FATAL_FAILED = Counter(
    "posthog_session_recordings_embeddings_fatal_failed",
    "Instance of the embeddings task failing and raising an exception",
    labelnames=["source_type"],
)

SESSION_EMBEDDINGS_WRITTEN_TO_CLICKHOUSE = Counter(
    "posthog_session_recordings_embeddings_written_to_clickhouse",
    "Number of session embeddings written to Clickhouse",
    labelnames=["source_type"],
)

SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS = Counter(
    "posthog_session_recordings_skipped_when_generating_embeddings",
    "Number of sessions skipped when generating embeddings",
    labelnames=["source_type", "reason"],
)

SESSION_EMBEDDINGS_FAILED_TO_CLICKHOUSE = Counter(
    "posthog_session_recordings_embeddings_failed_to_clickhouse",
    "Number of session embeddings failed to Clickhouse",
    labelnames=["source_type"],
)


logger = get_logger(__name__)


class EmbeddingPreparation(ABC):
    source_type: str

    @staticmethod
    @abstractmethod
    def prepare(item, team) -> tuple[str, str]:
        raise NotImplementedError()


class SessionEmbeddingsRunner(ABC):
    team: Team
    openai_client: Any

    def __init__(self, team: Team):
        self.team = team
        self.openai_client = OpenAI()

    def run(self, items: list[Any], embeddings_preparation: type[EmbeddingPreparation]) -> None:
        source_type = embeddings_preparation.source_type

        try:
            batched_embeddings = []

            for item in items:
                try:
                    logger.info(
                        f"generating embedding input for item",
                        flow="embeddings",
                        item=json.dumps(item),
                        source_type=source_type,
                    )

                    result = embeddings_preparation.prepare(item, self.team)

                    if result:
                        session_id, input = result

                        logger.info(
                            f"generating embedding for item",
                            flow="embeddings",
                            session_id=session_id,
                            source_type=source_type,
                        )

                        with GENERATE_RECORDING_EMBEDDING_TIMING.labels(source_type=source_type).time():
                            embeddings = self._embed(input, source_type=source_type)

                        logger.info(
                            f"generated embedding for item",
                            flow="embeddings",
                            session_id=session_id,
                            source_type=source_type,
                        )

                        if embeddings:
                            SESSION_EMBEDDINGS_GENERATED.labels(source_type=source_type).inc()
                            batched_embeddings.append(
                                {
                                    "team_id": self.team.pk,
                                    "session_id": session_id,
                                    "embeddings": embeddings,
                                    "source_type": source_type,
                                    "input": input,
                                }
                            )
                # we don't want to fail the whole batch if only a single recording fails
                except Exception as e:
                    SESSION_EMBEDDINGS_FAILED.labels(source_type=source_type).inc()
                    logger.exception(
                        f"embed individual item error",
                        flow="embeddings",
                        error=e,
                        source_type=source_type,
                    )
                    # so we swallow errors here

            if len(batched_embeddings) > 0:
                self._flush_embeddings_to_clickhouse(embeddings=batched_embeddings, source_type=source_type)
        except Exception as e:
            # but we don't swallow errors within the wider task itself
            # if something is failing here then we're most likely having trouble with ClickHouse
            SESSION_EMBEDDINGS_FATAL_FAILED.labels(source_type=source_type).inc()
            logger.exception(f"embed items fatal error", flow="embeddings", error=e, source_type=source_type)
            raise

    def _embed(self, input: str, source_type: str):
        token_count = self._num_tokens_for_input(input)
        RECORDING_EMBEDDING_TOKEN_COUNT.labels(source_type=source_type).observe(token_count)
        if token_count > MAX_TOKENS_FOR_MODEL:
            logger.error(
                f"embedding input exceeds max token count for model",
                flow="embeddings",
                input=json.dumps(input),
                source_type=source_type,
            )
            SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.labels(
                source_type=source_type, reason="token_count_too_high"
            ).inc()
            return None

        return (
            self.openai_client.embeddings.create(
                input=input,
                model="text-embedding-3-small",
            )
            .data[0]
            .embedding
        )

    def _num_tokens_for_input(self, string: str) -> int:
        """Returns the number of tokens in a text string."""
        return len(get_encoding().encode(string))

    def _flush_embeddings_to_clickhouse(self, embeddings: list[dict[str, Any]], source_type: str) -> None:
        try:
            sync_execute(
                "INSERT INTO session_replay_embeddings (session_id, team_id, embeddings, source_type, input) VALUES",
                embeddings,
            )
            SESSION_EMBEDDINGS_WRITTEN_TO_CLICKHOUSE.labels(source_type=source_type).inc(len(embeddings))
        except Exception as e:
            logger.exception(f"flush embeddings error", flow="embeddings", error=e, source_type=source_type)
            SESSION_EMBEDDINGS_FAILED_TO_CLICKHOUSE.labels(source_type=source_type).inc(len(embeddings))
            raise


class ErrorEmbeddingsPreparation(EmbeddingPreparation):
    source_type = "error"

    @staticmethod
    def prepare(item: tuple[str, str], _):
        session_id = item[0]
        error_message = item[1]
        return session_id, error_message


class SessionEventsEmbeddingsPreparation(EmbeddingPreparation):
    source_type = "session"

    @staticmethod
    def prepare(session_id: str, team: Team):
        eight_days_ago = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=8)
        session_metadata = SessionReplayEvents().get_metadata(
            session_id=str(session_id), team=team, recording_start_time=eight_days_ago
        )
        if not session_metadata:
            logger.error(f"no session metadata found for session", flow="embeddings", session_id=session_id)
            SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.labels(
                source_type=SessionEventsEmbeddingsPreparation.source_type, reason="metadata_missing"
            ).inc()
            return None

        session_events = SessionReplayEvents().get_events(
            session_id=str(session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )

        if not session_events or not session_events[0] or not session_events[1]:
            logger.error(f"no events found for session", flow="embeddings", session_id=session_id)
            SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.labels(
                source_type=SessionEventsEmbeddingsPreparation.source_type, reason="events_missing"
            ).inc()
            return None

        processed_sessions = collapse_sequence_of_events(
            only_pageview_urls(
                format_dates(
                    simplify_window_id(SessionSummaryPromptData(columns=session_events[0], results=session_events[1])),
                    start=datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC),  # epoch timestamp
                )
            )
        )

        logger.info(f"collapsed events for session", flow="embeddings", session_id=session_id)

        processed_sessions_index = processed_sessions.column_index("event")
        current_url_index = processed_sessions.column_index("$current_url")
        elements_chain_index = processed_sessions.column_index("elements_chain")

        input = (
            str(session_metadata)
            + "\n"
            + "\n".join(
                SessionEventsEmbeddingsPreparation._compact_result(
                    event_name=result[processed_sessions_index] if processed_sessions_index is not None else "",
                    current_url=result[current_url_index] if current_url_index is not None else "",
                    elements_chain=result[elements_chain_index] if elements_chain_index is not None else "",
                )
                for result in processed_sessions.results
            )
        )

        return session_id, input

    @staticmethod
    def _compact_result(event_name: str, current_url: int, elements_chain: dict[str, str] | str) -> str:
        elements_string = (
            elements_chain if isinstance(elements_chain, str) else ", ".join(str(e) for e in elements_chain)
        )
        return f"{event_name} {current_url} {elements_string}"
