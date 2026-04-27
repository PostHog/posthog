"""Wire schema for flags_cache_invalidation Kafka messages.

Producer: Django signal handlers in posthog/models/feature_flag/flags_cache.py.
Consumer: rust/feature-flags flags-cache-builder.

The fixture at rust/feature-flags/tests/fixtures/flags_cache_invalidation_v1.json
is the contract — both sides round-trip against it in CI so schema drift fails
the build on either side. Bumping `version` requires running both producers
(old + new) and both consumers (old + new) in parallel during the migration —
do not bump it without a written rollout plan.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FlagsCacheInvalidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    team_id: int
    operation: Literal["invalidate"] = "invalidate"
    emitted_at: datetime
