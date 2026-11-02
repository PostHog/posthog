from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.api.capture import CaptureInternalResult

from products.autoresearch.backend.dataset.labeling import PREDICTION_EVENT_NAME
from products.autoresearch.backend.inference import person_property
from products.autoresearch.backend.inference.person_property import STOP_REENABLED, remove_output_person_property
from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.testing import TeamScopedTestMixin

_PROPERTY = "predicted_p_pageview_7d"


class TestRemoveOutputPersonProperty(TeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("removes_from_every_holder", None),
            ("stops_when_turned_back_on", _PROPERTY),
            ("continues_when_turned_back_on_for_another_name", "renamed_score"),
        ]
    )
    def test_unsets_the_property_on_persons_that_hold_it(self, _name: str, reenable_with: str | None):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Cleanup",
            target_event="$pageview",
            output_person_property=_PROPERTY,
            write_person_property=False,
        )
        for distinct_id in ("holder-1", "holder-2"):
            holder = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={_PROPERTY: 0.4})
            _create_event(
                team=self.team,
                event=PREDICTION_EVENT_NAME,
                distinct_id=distinct_id,
                properties={
                    "$autoresearch_pipeline_id": str(pipeline.pk),
                    "$autoresearch_model_role": "champion",
                    "$autoresearch_person_id": str(holder.uuid),
                    "$set": {_PROPERTY: 0.4},
                },
            )
        # Holds the same property from another source, and this pipeline never scored them.
        _create_person(team_id=self.team.pk, distinct_ids=["bystander"], properties={_PROPERTY: 0.9})
        # Scored while writing was off, so the property they hold is their own.
        scored_while_off = _create_person(
            team_id=self.team.pk, distinct_ids=["scored-while-off"], properties={_PROPERTY: 0.7}
        )
        _create_event(
            team=self.team,
            event=PREDICTION_EVENT_NAME,
            distinct_id="scored-while-off",
            properties={
                "$autoresearch_pipeline_id": str(pipeline.pk),
                "$autoresearch_model_role": "champion",
                "$autoresearch_person_id": str(scored_while_off.uuid),
            },
        )
        flush_persons_and_events()

        def accept(**kwargs: object) -> CaptureInternalResult:
            if reenable_with is not None:
                AutoresearchPipeline.objects.filter(pk=pipeline.pk).update(
                    write_person_property=True, output_person_property=reenable_with
                )
            return CaptureInternalResult(status_code=200)

        capture = MagicMock(side_effect=accept)
        # One person per page, so the re-enable lands between the two holders.
        with (
            patch.object(person_property, "CLEANUP_PAGE_SIZE", 1),
            patch.object(person_property, "capture_batch_internal", capture),
        ):
            outcome = remove_output_person_property(
                team=self.team,
                pipeline_id=str(pipeline.pk),
                output_property=_PROPERTY,
                user=self.user,
                written_since=pipeline.created_at.isoformat(),
            )

        events = [event for call in capture.call_args_list for event in call.kwargs["events"]]
        assert all(event["properties"]["$unset"] == [_PROPERTY] for event in events)
        assert all(call.kwargs["process_person_profile"] for call in capture.call_args_list)
        unset_for = {event["distinct_id"] for event in events}
        if reenable_with == _PROPERTY:
            assert len(unset_for) == 1 and unset_for < {"holder-1", "holder-2"}
            assert outcome.stopped == STOP_REENABLED
        else:
            assert unset_for == {"holder-1", "holder-2"}
            assert outcome.stopped is None
        assert outcome.persons_cleared == len(unset_for)
