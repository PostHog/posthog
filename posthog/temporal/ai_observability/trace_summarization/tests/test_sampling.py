import uuid
import datetime as dt

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models import PropertyDefinition
from posthog.temporal.ai_observability.trace_summarization.sampling import _sample_items

WINDOW_START = dt.datetime(2026, 1, 15, 10, 0, tzinfo=dt.UTC)
WINDOW_END = WINDOW_START + dt.timedelta(hours=1)
EVENT_TIMESTAMP = WINDOW_START + dt.timedelta(minutes=5)


class TestSampling(ClickhouseTestMixin, BaseTest):
    @parameterized.expand([("trace",), ("generation",)])
    def test_samples_trace_id_that_a_team_defined_as_datetime(self, analysis_level: str) -> None:
        # A timestamp-shaped trace id makes the type detection classify the property as
        # DateTime for the whole team, which made the sampling query parse every id as a
        # date and fail on the empty-string comparison.
        trace_id = "2026-01-15 09:59:59.123456"
        PropertyDefinition.objects.create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$ai_trace_id",
            property_type="DateTime",
        )
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id="user-1",
            timestamp=EVENT_TIMESTAMP,
            event_uuid=uuid.uuid4(),
            properties={"$ai_trace_id": trace_id},
        )
        flush_persons_and_events()

        items = _sample_items(
            team_id=self.team.pk,
            window_start=WINDOW_START.isoformat(),
            window_end=WINDOW_END.isoformat(),
            max_items=10,
            analysis_level=analysis_level,
        )

        assert [item.trace_id for item in items] == [trace_id]
