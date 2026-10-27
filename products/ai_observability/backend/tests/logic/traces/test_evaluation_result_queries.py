from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models import Team
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.evaluation_result_queries import load_evaluation_results

from .rows import T0, make_evaluation_result_event

LATE = "00000000-0000-0000-0000-00000000000b"
EARLY = "00000000-0000-0000-0000-00000000000a"


class TestLoadEvaluationResults(ClickhouseTestMixin, BaseTest):
    def test_reads_every_result_of_the_trace_however_late_it_was_stamped(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        bulk_create_events(
            [
                make_evaluation_result_event(uuid=EARLY, team=self.team, timestamp=T0 + timedelta(seconds=1)),
                make_evaluation_result_event(uuid=LATE, team=self.team, timestamp=T0 + timedelta(days=90)),
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-00000000000c",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    trace_id="trace-2",
                ),
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-00000000000d", team=other_team, timestamp=T0 + timedelta(seconds=1)
                ),
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-00000000000e", team=self.team, timestamp=T0, event="$ai_generation"
                ),
            ]
        )

        assert [row.uuid for row in load_evaluation_results(self.team, None, "trace-1")] == [LATE, EARLY]
