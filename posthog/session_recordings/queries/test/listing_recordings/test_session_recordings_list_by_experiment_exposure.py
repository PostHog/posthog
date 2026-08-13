from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    filter_recordings_by,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FROZEN_NOW = "2021-08-21T20:00:00Z"
BASE_TIME = datetime(2021, 8, 21, 10, 0, tzinfo=UTC)


@freeze_time(FROZEN_NOW)
class TestSessionRecordingsListByExperimentExposure(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    def _create_experiment(
        self,
        exposure_criteria: dict | None = None,
        flag_filters: dict | None = None,
        start_date: datetime | None = BASE_TIME - timedelta(days=1),
        key: str = "recordings-linkage-flag",
    ) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            filters=flag_filters
            or {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        return Experiment.objects.create(
            team=self.team,
            name=f"experiment for {key}",
            feature_flag=flag,
            created_by=self.user,
            start_date=start_date,
            exposure_criteria=exposure_criteria or {},
            metrics=[],
        )

    def _create_exposure_event(
        self,
        distinct_id: str,
        timestamp: datetime,
        variant: str,
        flag_key: str = "recordings-linkage-flag",
        person_uuid: str | None = None,
        event: str = "$feature_flag_called",
        properties: dict | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$feature_flag": flag_key,
                "$feature_flag_response": variant,
                **(properties or {}),
            },
            **({"person_id": person_uuid} if person_uuid else {}),
        )

    def _produce_recording(self, distinct_id: str, session_id: str, start: datetime, end: datetime) -> None:
        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=start,
            last_timestamp=end,
        )

    def _assert_query_matches_session_ids(self, query: dict, expected: list[str]) -> None:
        assert_query_matches_session_ids(team=self.team, query=query, expected=expected)

    def test_filters_to_sessions_of_exposed_persons_ending_at_or_after_first_exposure(self) -> None:
        experiment = self._create_experiment()
        create_person(team=self.team, distinct_ids=["exposed-user"])
        create_person(team=self.team, distinct_ids=["other-user"])
        exposure_time = BASE_TIME + timedelta(hours=2)
        self._create_exposure_event("exposed-user", exposure_time, "test")
        flush_persons_and_events()

        self._produce_recording(
            "exposed-user",
            "session-after",
            exposure_time + timedelta(hours=1),
            exposure_time + timedelta(hours=1, minutes=10),
        )
        self._produce_recording(
            "exposed-user",
            "session-spanning",
            exposure_time - timedelta(minutes=10),
            exposure_time + timedelta(minutes=30),
        )
        self._produce_recording("exposed-user", "session-ended-before", BASE_TIME, BASE_TIME + timedelta(minutes=30))
        self._produce_recording(
            "other-user",
            "session-of-unexposed",
            exposure_time + timedelta(hours=1),
            exposure_time + timedelta(hours=1, minutes=10),
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-after", "session-spanning"],
        )

    def test_filters_by_variant(self) -> None:
        experiment = self._create_experiment()
        create_person(team=self.team, distinct_ids=["control-user"])
        create_person(team=self.team, distinct_ids=["test-user"])
        exposure_time = BASE_TIME + timedelta(hours=2)
        self._create_exposure_event("control-user", exposure_time, "control")
        self._create_exposure_event("test-user", exposure_time, "test")
        flush_persons_and_events()

        session_start = exposure_time + timedelta(hours=1)
        self._produce_recording("control-user", "session-control", session_start, session_start + timedelta(minutes=10))
        self._produce_recording("test-user", "session-test", session_start, session_start + timedelta(minutes=10))

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id, "variant": "test"}},
            ["session-test"],
        )
        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-control", "session-test"],
        )

    def test_links_server_side_exposures_through_the_person(self) -> None:
        # The case the person-scoped linkage exists for: the exposure event is captured
        # server-side under a backend distinct id and without a usable $session_id, while the
        # recording belongs to the same person's browser distinct id.
        experiment = self._create_experiment()
        person = create_person(team=self.team, distinct_ids=["server-side-id", "browser-id"])
        exposure_time = BASE_TIME + timedelta(hours=2)
        self._create_exposure_event("server-side-id", exposure_time, "test", person_uuid=str(person.uuid))
        flush_persons_and_events()

        session_start = exposure_time + timedelta(hours=1)
        self._produce_recording(
            "browser-id", "session-on-browser", session_start, session_start + timedelta(minutes=10)
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-on-browser"],
        )

    def test_excludes_persons_exposed_to_multiple_variants(self) -> None:
        # Default multiple-variant handling is "exclude": the analysis counts these persons in
        # no variant, so their sessions must not appear as exposed either.
        experiment = self._create_experiment()
        create_person(team=self.team, distinct_ids=["contaminated-user"])
        self._create_exposure_event("contaminated-user", BASE_TIME + timedelta(hours=1), "control")
        self._create_exposure_event("contaminated-user", BASE_TIME + timedelta(hours=2), "test")
        flush_persons_and_events()

        session_start = BASE_TIME + timedelta(hours=3)
        self._produce_recording(
            "contaminated-user", "session-contaminated", session_start, session_start + timedelta(minutes=10)
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            [],
        )

    def test_activation_mode_counts_exposure_from_the_activation_event(self) -> None:
        experiment = self._create_experiment(
            exposure_criteria={
                "activation_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "task_completed",
                    "properties": [],
                }
            }
        )
        create_person(team=self.team, distinct_ids=["activated-user"])
        flag_exposure_time = BASE_TIME + timedelta(minutes=30)
        activation_time = BASE_TIME + timedelta(hours=3)
        self._create_exposure_event("activated-user", flag_exposure_time, "test")
        _create_event(
            team=self.team,
            event="task_completed",
            distinct_id="activated-user",
            timestamp=activation_time,
            properties={},
        )
        flush_persons_and_events()

        self._produce_recording(
            "activated-user",
            "session-before-activation",
            BASE_TIME + timedelta(hours=1),
            BASE_TIME + timedelta(hours=1, minutes=30),
        )
        self._produce_recording(
            "activated-user",
            "session-after-activation",
            activation_time + timedelta(minutes=30),
            activation_time + timedelta(minutes=45),
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-after-activation"],
        )

    def test_custom_exposure_event_defines_the_exposure_moment(self) -> None:
        experiment = self._create_experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout_started",
                    "properties": [],
                }
            }
        )
        create_person(team=self.team, distinct_ids=["custom-exposed-user"])
        flag_call_time = BASE_TIME + timedelta(minutes=30)
        custom_exposure_time = BASE_TIME + timedelta(hours=3)
        # The flag-called event must not count as exposure for custom criteria.
        self._create_exposure_event("custom-exposed-user", flag_call_time, "test")
        # Custom exposure events carry the variant in the stamped flag property.
        _create_event(
            team=self.team,
            event="checkout_started",
            distinct_id="custom-exposed-user",
            timestamp=custom_exposure_time,
            properties={"$feature/recordings-linkage-flag": "test"},
        )
        flush_persons_and_events()

        self._produce_recording(
            "custom-exposed-user",
            "session-before-custom",
            BASE_TIME + timedelta(hours=1),
            BASE_TIME + timedelta(hours=1, minutes=30),
        )
        self._produce_recording(
            "custom-exposed-user",
            "session-after-custom",
            custom_exposure_time + timedelta(minutes=30),
            custom_exposure_time + timedelta(minutes=45),
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-after-custom"],
        )

    def test_rejects_experiments_the_linkage_cannot_answer_for(self) -> None:
        with self.assertRaises(ValidationError):
            filter_recordings_by(team=self.team, recordings_filter={"experiment_exposure": {"experiment_id": 999999}})

        draft = self._create_experiment(start_date=None, key="draft-flag")
        with self.assertRaises(ValidationError):
            filter_recordings_by(team=self.team, recordings_filter={"experiment_exposure": {"experiment_id": draft.id}})

        group_scoped = self._create_experiment(
            key="group-flag",
            flag_filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "aggregation_group_type_index": 0,
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        with self.assertRaises(ValidationError):
            filter_recordings_by(
                team=self.team, recordings_filter={"experiment_exposure": {"experiment_id": group_scoped.id}}
            )

        experiment = self._create_experiment(key="variant-check-flag")
        with self.assertRaises(ValidationError):
            filter_recordings_by(
                team=self.team,
                recordings_filter={"experiment_exposure": {"experiment_id": experiment.id, "variant": "nope"}},
            )

    def test_composes_with_event_filters(self) -> None:
        experiment = self._create_experiment()
        create_person(team=self.team, distinct_ids=["exposed-user"])
        exposure_time = BASE_TIME + timedelta(hours=1)
        self._create_exposure_event("exposed-user", exposure_time, "test")

        with_event_session = "session-with-purchase"
        without_event_session = "session-without-purchase"
        first_session_start = exposure_time + timedelta(hours=1)
        second_session_start = exposure_time + timedelta(hours=2)
        _create_event(
            team=self.team,
            event="purchase_completed",
            distinct_id="exposed-user",
            timestamp=first_session_start + timedelta(minutes=1),
            properties={"$session_id": with_event_session},
        )
        flush_persons_and_events()

        self._produce_recording(
            "exposed-user", with_event_session, first_session_start, first_session_start + timedelta(minutes=10)
        )
        self._produce_recording(
            "exposed-user", without_event_session, second_session_start, second_session_start + timedelta(minutes=10)
        )

        self._assert_query_matches_session_ids(
            {
                "experiment_exposure": {"experiment_id": experiment.id},
                "events": [{"id": "purchase_completed", "type": "events", "name": "purchase_completed"}],
            },
            [with_event_session],
        )
        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            [with_event_session, without_event_session],
        )
