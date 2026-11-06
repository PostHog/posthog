import json
import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import field
from datetime import UTC, datetime
from hashlib import sha256
from threading import Event, Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from redis import Redis

# Bump when PromptJevRunner's prompt/batching contract or question input serialization changes.
EVALUATOR_VERSION = 1
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_CACHE_BATCH = 256
DEFAULT_LEASE_SECONDS = 60
# Renewal runs every half lease, so the default covers 60 + 6 * 30 = 240 seconds. Coverage must outlast
# the chunk evaluator's inference wait, or a slow batch loses its lease and the retry pays for it again.
DEFAULT_MAX_RENEWALS = 6


class DecisionCacheUnavailable(RuntimeError):
    pass


@frozen
class DecisionRequest:
    input: str = field(repr=False)
    question_schema: str = field(repr=False)
    model_id: str
    model_revision: str
    evaluator_version: int = EVALUATOR_VERSION

    def key(self, team_id: int) -> str:
        if team_id <= 0 or not self.model_id.strip() or not self.model_revision.strip() or self.evaluator_version < 1:
            raise ValueError("A decision needs a project, immutable model revision, and evaluator version.")
        canonical = json.dumps(
            {
                "input": self.input,
                "question_schema": json.loads(self.question_schema),
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "evaluator_version": self.evaluator_version,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        return f"dq:jev:v1:{team_id}:{sha256(canonical.encode()).hexdigest()}"


class CachedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    model_revision: str = Field(min_length=1)
    evaluator_version: int = Field(ge=1)
    evaluated_at: datetime


@frozen
class DecisionLease:
    key: str
    token: str
    renewals: int = 0


_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_PUBLISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('DEL', KEYS[1])
return 1
"""


class JevDecisionCache:
    def __init__(
        self,
        client: "Redis",
        *,
        team_id: int,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_renewals: int = DEFAULT_MAX_RENEWALS,
    ) -> None:
        if team_id <= 0 or ttl_seconds <= 0 or lease_seconds <= 0 or max_renewals < 0:
            raise ValueError("Invalid decision cache configuration.")
        self.client = client
        self.team_id = team_id
        self.ttl_seconds = ttl_seconds
        self.lease_seconds = lease_seconds
        self.max_renewals = max_renewals

    def read(self, requests: Sequence[DecisionRequest]) -> dict[str, float]:
        decisions: dict[str, float] = {}
        try:
            for start in range(0, len(requests), MAX_CACHE_BATCH):
                batch = requests[start : start + MAX_CACHE_BATCH]
                keys = [request.key(self.team_id) for request in batch]
                values = self.client.mget(keys)
                for request, key, value in zip(batch, keys, values, strict=True):
                    if value is None:
                        continue
                    try:
                        decision = CachedDecision.model_validate_json(value)
                    except (ValidationError, ValueError, TypeError):
                        continue
                    if (
                        decision.model_revision == request.model_revision
                        and decision.evaluator_version == request.evaluator_version
                        and decision.evaluated_at.tzinfo is not None
                    ):
                        decisions[key] = decision.probability
        except RedisError as error:
            raise DecisionCacheUnavailable("Redis decision cache is unavailable.") from error
        return decisions

    def acquire(self, requests: Sequence[DecisionRequest]) -> dict[str, DecisionLease]:
        leases: dict[str, DecisionLease] = {}
        try:
            for start in range(0, len(requests), MAX_CACHE_BATCH):
                batch = requests[start : start + MAX_CACHE_BATCH]
                candidates = {
                    request.key(self.team_id): DecisionLease(key=request.key(self.team_id), token=uuid4().hex)
                    for request in batch
                }
                with self.client.pipeline(transaction=False) as pipeline:
                    for lease in candidates.values():
                        pipeline.set(lease.key + ":lease", lease.token, nx=True, ex=self.lease_seconds)
                    acquired = pipeline.execute()
                for lease, owned in zip(candidates.values(), acquired, strict=True):
                    if owned:
                        leases[lease.key] = lease
        except RedisError as error:
            # Leases from an interrupted pipeline expire without requiring cleanup to succeed.
            raise DecisionCacheUnavailable("Redis decision cache is unavailable.") from error
        return leases

    def renew(self, lease: DecisionLease) -> DecisionLease | None:
        return self.renew_many([lease]).get(lease.key)

    def renew_many(self, leases: Sequence[DecisionLease]) -> dict[str, DecisionLease]:
        renewable = [lease for lease in leases if lease.renewals < self.max_renewals]
        renewed: dict[str, DecisionLease] = {}
        try:
            for start in range(0, len(renewable), MAX_CACHE_BATCH):
                batch = renewable[start : start + MAX_CACHE_BATCH]
                with self.client.pipeline(transaction=False) as pipeline:
                    for lease in batch:
                        pipeline.eval(_RENEW, 1, lease.key + ":lease", lease.token, self.lease_seconds)
                    results = pipeline.execute()
                renewed.update(
                    {
                        lease.key: DecisionLease(key=lease.key, token=lease.token, renewals=lease.renewals + 1)
                        for lease, owned in zip(batch, results, strict=True)
                        if owned
                    }
                )
        except RedisError as error:
            raise DecisionCacheUnavailable("Redis decision cache is unavailable.") from error
        return renewed

    @contextmanager
    def maintain(self, leases: Sequence[DecisionLease]) -> Iterator[None]:
        stopped = Event()
        errors: list[DecisionCacheUnavailable] = []

        def renew_while_evaluating() -> None:
            active = list(leases)
            while active and not stopped.wait(self.lease_seconds / 2):
                try:
                    active = list(self.renew_many(active).values())
                except DecisionCacheUnavailable as error:
                    errors.append(error)
                    break

        worker = Thread(target=renew_while_evaluating, name="dq-jev-lease", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            worker.join()
        if errors:
            raise errors[0]

    def publish(self, decisions: Sequence[tuple[DecisionLease, DecisionRequest, float]]) -> set[str]:
        published: set[str] = set()
        # Validate the whole batch before writing any of it.
        values: list[str] = []
        for lease, request, probability in decisions:
            if lease.key != request.key(self.team_id) or type(probability) not in (int, float):
                raise ValueError("Invalid decision publication.")
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("Jev returned an invalid probability.")
            values.append(
                CachedDecision(
                    probability=float(probability),
                    model_revision=request.model_revision,
                    evaluator_version=request.evaluator_version,
                    evaluated_at=datetime.now(UTC),
                ).model_dump_json()
            )
        try:
            for start in range(0, len(decisions), MAX_CACHE_BATCH):
                batch = decisions[start : start + MAX_CACHE_BATCH]
                with self.client.pipeline(transaction=False) as pipeline:
                    for (lease, _, _), value in zip(batch, values[start : start + MAX_CACHE_BATCH], strict=True):
                        pipeline.eval(
                            _PUBLISH,
                            2,
                            lease.key + ":lease",
                            lease.key,
                            lease.token,
                            value,
                            self.ttl_seconds,
                        )
                    results = pipeline.execute()
                published.update(lease.key for (lease, _, _), owned in zip(batch, results, strict=True) if owned)
        except RedisError as error:
            raise DecisionCacheUnavailable("Redis decision cache is unavailable.") from error
        return published

    def release(self, leases: Sequence[DecisionLease]) -> None:
        try:
            for start in range(0, len(leases), MAX_CACHE_BATCH):
                with self.client.pipeline(transaction=False) as pipeline:
                    for lease in leases[start : start + MAX_CACHE_BATCH]:
                        pipeline.eval(_RELEASE, 1, lease.key + ":lease", lease.token)
                    pipeline.execute()
        except RedisError as error:
            raise DecisionCacheUnavailable("Redis decision cache is unavailable.") from error
