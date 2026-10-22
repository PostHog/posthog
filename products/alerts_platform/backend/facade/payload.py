"""How much of a batch fits in one Temporal payload.

Temporal rejects an activity input or result above about 2 MiB, and the whole batch fails with it
rather than the part that did not fit. The encryption codec base64-encodes each payload, which
adds a third, so a batch is held to half the limit before encoding.
"""

from collections.abc import Sequence
from typing import Final

import temporalio.converter

from products.alerts_platform.backend.facade.contracts import PlatformAlertOutcome

# Workflow code chunks by it, so a change alters how many activities a replay schedules and needs a patch.
MAX_BATCH_PAYLOAD_BYTES: Final = 1024 * 1024


def payload_bytes(value: object) -> int:
    """The size of `value` as the default converter encodes it, before the codec."""
    return temporalio.converter.default().payload_converter.to_payloads([value])[0].ByteSize()


def outcome_chunks(outcomes: Sequence[PlatformAlertOutcome]) -> list[tuple[PlatformAlertOutcome, ...]]:
    """The outcomes in order, cut into runs that each fit the budget.

    An outcome larger than the budget on its own still gets a run of its own, because the source
    already sent it across Temporal as one activity result.
    """
    chunks: list[tuple[PlatformAlertOutcome, ...]] = []
    current: list[PlatformAlertOutcome] = []
    spent = 0
    for outcome in outcomes:
        size = payload_bytes(outcome)
        if current and spent + size > MAX_BATCH_PAYLOAD_BYTES:
            chunks.append(tuple(current))
            current, spent = [], 0
        current.append(outcome)
        spent += size
    if current:
        chunks.append(tuple(current))
    return chunks
