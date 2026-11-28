"""Sends Django integration rows to `PUT /v1/integrations/mirror` of the credentials service.

The worker deployment (`posthog-worker-django`) signs the tokens: the service policy lets only that
deployment mirror. Each token is owned by the team of the rows it sends.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen
from posthog.integrations.backend.service_transport import IntegrationServiceError, ServiceTransport
from posthog.integrations.mirror.snapshot import MirrorRow

MIRROR_PATH = "/mirror"
MAX_ROWS_PER_REQUEST = 100
# Half of the 1 MB body limit of the service. A row larger than this goes alone.
MAX_BODY_BYTES = 512 * 1024
# The `code` of a `conflict` that lost a race twice inside the service. A later retry can succeed.
CONCURRENT_WRITE = "concurrent_write"


class MirrorOrigin(StrEnum):
    WRITE = "write"
    RETRY = "retry"
    BACKFILL = "backfill"
    REPAIR = "repair"


class MirrorOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    UNCHANGED = "unchanged"
    STALE = "stale"
    ABSENT = "absent"
    CONFLICT = "conflict"
    OWNER_MISMATCH = "owner_mismatch"
    REJECTED = "rejected"


@frozen
class MirrorResult:
    legacy_id: int
    outcome: MirrorOutcome
    id: str | None = None
    # Set with a key `conflict`. None when the row that holds the key did not come from the mirror.
    conflicting_legacy_id: int | None = None
    code: str | None = None

    @property
    def retryable(self) -> bool:
        return self.outcome == MirrorOutcome.CONFLICT and self.code == CONCURRENT_WRITE


def _encoded_size(value: Any) -> int:
    # The separators and ASCII escaping that `requests` uses for `json=`.
    return len(json.dumps(value))


def batches(bodies: Sequence[Mapping[str, Any]], *, origin: MirrorOrigin, force: bool) -> Iterator[list[Any]]:
    """Splits row bodies into requests of at most `MAX_ROWS_PER_REQUEST` rows and about `MAX_BODY_BYTES`."""
    envelope = _encoded_size({"origin": origin.value, "force": force, "rows": []})
    batch: list[Any] = []
    size = envelope
    for body in bodies:
        row_size = _encoded_size(body) + len(", ")
        if batch and (len(batch) >= MAX_ROWS_PER_REQUEST or size + row_size > MAX_BODY_BYTES):
            yield batch
            batch, size = [], envelope
        batch.append(body)
        size += row_size
    if batch:
        yield batch


def _parse_result(body: Any) -> MirrorResult:
    try:
        conflicting = body.get("conflicting_legacy_id")
        return MirrorResult(
            legacy_id=int(body["legacy_id"]),
            outcome=MirrorOutcome(body["outcome"]),
            id=body.get("id"),
            conflicting_legacy_id=None if conflicting is None else int(conflicting),
            code=body.get("code"),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise IntegrationServiceError(
            "bad_response", "the mirror route answered a result it does not document"
        ) from error


class MirrorClient:
    def __init__(self, transport: ServiceTransport | None = None) -> None:
        self._transport = transport or ServiceTransport()

    def mirror(
        self, team_id: int, rows: Sequence[MirrorRow], *, origin: MirrorOrigin, force: bool = False
    ) -> list[MirrorResult]:
        """Mirrors rows of one team. Raises `IntegrationServiceUnavailable` when the service fails or is unreachable."""
        results: list[MirrorResult] = []
        for batch in batches([row.to_body() for row in rows], origin=origin, force=force):
            token = self._transport.token("mirror", team_id=team_id, kinds={row["kind"] for row in batch})
            answer = self._transport.json(
                "PUT", MIRROR_PATH, token, body={"origin": origin.value, "force": force, "rows": batch}
            )
            answered = answer.get("results") if isinstance(answer, dict) else None
            if not isinstance(answered, list) or len(answered) != len(batch):
                raise IntegrationServiceError("bad_response", "the mirror route did not answer one result per row")
            results.extend(_parse_result(result) for result in answered)
        return results
