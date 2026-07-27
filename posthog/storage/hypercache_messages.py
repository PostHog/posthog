"""Wire schema for hypercache cache-ready signals.

Producer: HyperCache._publish_ready_signal in posthog/storage/hypercache.py.
Consumer: the flags-stream-gateway (Rust) hint subscriber.

The fixture at rust/feature-flags/tests/fixtures/hypercache_ready_v1.json is the
contract. The Python producer round-trips against it strictly in
posthog/storage/test/test_hypercache_messages.py; the gateway consumer parses it
leniently (unknown fields tolerated) because the hint is at-most-once and
sweep-backed. Bumping `v` requires a written rollout plan across both the producer
and the consumer.
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


class HypercacheReadySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    team_id: int
    namespace: str
    value: str
    etag: str
    # AwareDatetime rejects naive datetimes — the wire contract is UTC and the
    # gateway consumer expects a timezone offset.
    written_at: AwareDatetime
