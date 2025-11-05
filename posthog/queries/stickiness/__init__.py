from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.stickiness import (
        ClickhouseStickiness as Stickiness,
        ClickhouseStickinessActors as StickinessActors,
    )
else:
    from posthog.queries.stickiness.stickiness import Stickiness  # type: ignore # noqa: F401
    from posthog.queries.stickiness.stickiness_actors import StickinessActors  # type: ignore  # noqa: F401
