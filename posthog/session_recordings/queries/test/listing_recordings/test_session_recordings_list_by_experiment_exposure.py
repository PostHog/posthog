import json
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rbac.user_access_control import UserAccessControlError
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.queries.recordings_query_runner import RecordingsQueryRunner
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    filter_recordings_by,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_api import list_recordings_from_query
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.models.rbac.access_control import AccessControl

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
        excluded_variants: list[str] | None = None,
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
            excluded_variants=excluded_variants,
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
        assert_query_matches_session_ids(team=self.team, query=query, expected=expected, user=self.user)

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

    def test_excluded_variants_are_invisible_to_the_linkage(self) -> None:
        experiment = self._create_experiment(
            flag_filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 25},
                        {"key": "beta", "rollout_percentage": 25},
                    ]
                },
            },
            excluded_variants=["beta"],
        )
        create_person(team=self.team, distinct_ids=["beta-only-user"])
        create_person(team=self.team, distinct_ids=["control-and-beta-user"])
        exposure_time = BASE_TIME + timedelta(hours=1)
        self._create_exposure_event("beta-only-user", exposure_time, "beta")
        # Exposures to an excluded variant are invisible to the analysis, so this person
        # attributes cleanly to control rather than counting as multiple-variant.
        self._create_exposure_event("control-and-beta-user", exposure_time, "control")
        self._create_exposure_event("control-and-beta-user", exposure_time + timedelta(minutes=5), "beta")
        flush_persons_and_events()

        session_start = exposure_time + timedelta(hours=1)
        self._produce_recording(
            "beta-only-user", "session-of-beta-only", session_start, session_start + timedelta(minutes=10)
        )
        self._produce_recording(
            "control-and-beta-user", "session-of-control", session_start, session_start + timedelta(minutes=10)
        )

        self._assert_query_matches_session_ids(
            {"experiment_exposure": {"experiment_id": experiment.id}},
            ["session-of-control"],
        )
        with self.assertRaises(ValidationError):
            filter_recordings_by(
                team=self.team,
                recordings_filter={"experiment_exposure": {"experiment_id": experiment.id, "variant": "beta"}},
                user=self.user,
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

    @parameterized.expand(
        [
            ("unknown_experiment", None, None),
            ("draft_experiment", {"start_date": None, "key": "draft-flag"}, None),
            (
                "group_aggregated_experiment",
                {
                    "key": "group-flag",
                    "flag_filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "aggregation_group_type_index": 0,
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                    },
                },
                None,
            ),
            ("unknown_variant", {"key": "variant-check-flag"}, "nope"),
        ]
    )
    def test_rejects_experiments_the_linkage_cannot_answer_for(
        self, _name: str, experiment_kwargs: dict | None, variant: str | None
    ) -> None:
        experiment_id = self._create_experiment(**experiment_kwargs).id if experiment_kwargs is not None else 999999
        exposure_filter: dict = {"experiment_id": experiment_id}
        if variant is not None:
            exposure_filter["variant"] = variant

        with self.assertRaises(ValidationError):
            filter_recordings_by(
                team=self.team, recordings_filter={"experiment_exposure": exposure_filter}, user=self.user
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

    def test_persisted_pinned_recordings_still_go_through_the_exposure_filter(self) -> None:
        # Recordings persisted to S3 are normally served straight from Postgres when queried by
        # session id, skipping the ClickHouse query the exposure join lives in; with the filter
        # set they must take the ClickHouse path so unexposed persons' sessions stay out.
        experiment = self._create_experiment()
        create_person(team=self.team, distinct_ids=["exposed-user"])
        create_person(team=self.team, distinct_ids=["other-user"])
        exposure_time = BASE_TIME + timedelta(hours=1)
        self._create_exposure_event("exposed-user", exposure_time, "test")
        flush_persons_and_events()

        session_start = exposure_time + timedelta(hours=1)
        self._produce_recording(
            "exposed-user", "session-of-exposed", session_start, session_start + timedelta(minutes=10)
        )
        self._produce_recording(
            "other-user", "session-of-unexposed", session_start, session_start + timedelta(minutes=10)
        )
        for session_id in ("session-of-exposed", "session-of-unexposed"):
            SessionRecording.objects.create(
                team=self.team, session_id=session_id, full_recording_v2_path=f"s3://bucket/{session_id}"
            )

        result = list_recordings_from_query(
            RecordingsQuery.model_validate(
                {
                    "session_ids": ["session-of-exposed", "session-of-unexposed"],
                    "experiment_exposure": {"experiment_id": experiment.id},
                }
            ),
            user=self.user,
            team=self.team,
        )

        assert [recording.session_id for recording in result.recordings] == ["session-of-exposed"]

    def _create_denied_experiment_and_viewer(self) -> tuple[Experiment, User]:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        experiment = self._create_experiment()
        AccessControl.objects.create(
            team=self.team, resource="experiment", resource_id=str(experiment.pk), access_level="none"
        )
        return experiment, self._create_user("denied-viewer@posthog.com")

    def test_denies_viewers_the_experiment_denies(self) -> None:
        # The filter reveals which recordings belong to an experiment's exposed persons, so a
        # viewer barred from the experiment must not be able to list them.
        experiment, denied_viewer = self._create_denied_experiment_and_viewer()
        query = RecordingsQuery.model_validate({"experiment_exposure": {"experiment_id": experiment.id}})

        with self.assertRaises(PermissionDenied):
            SessionRecordingListFromQuery(
                team=self.team, query=query, hogql_query_modifiers=None, user=denied_viewer
            ).run()

        # The creator keeps access despite the team-wide "none".
        result = SessionRecordingListFromQuery(
            team=self.team, query=query, hogql_query_modifiers=None, user=self.user
        ).run()
        assert result.results == []

    def test_refuses_userless_callers(self) -> None:
        # Userless background jobs (the playlist counting task, scanner sweeps) cache or surface
        # their output to viewers this check never evaluated, so the filter fails closed without
        # a viewer, regardless of the experiment's access controls.
        experiment = self._create_experiment()
        query = RecordingsQuery.model_validate({"experiment_exposure": {"experiment_id": experiment.id}})

        with self.assertRaises(PermissionDenied):
            SessionRecordingListFromQuery(team=self.team, query=query, hogql_query_modifiers=None, user=None).run()

    def test_query_runner_refuses_denied_viewers_before_running(self) -> None:
        # The generic query endpoint serves cached responses without rebuilding the query, so
        # only the runner-level hook keeps a denied viewer from reading a cached list.
        experiment, denied_viewer = self._create_denied_experiment_and_viewer()
        runner = RecordingsQueryRunner(
            query=RecordingsQuery.model_validate({"experiment_exposure": {"experiment_id": experiment.id}}),
            team=self.team,
        )

        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(denied_viewer)

        # Without the filter there is no experiment to protect; the same viewer passes.
        unfiltered = RecordingsQueryRunner(query=RecordingsQuery.model_validate({}), team=self.team)
        assert unfiltered.validate_query_runner_access(denied_viewer) is True

    @parameterized.expand(
        [
            ("query_scope_only", ["query:read"], True, 403),
            ("with_experiment_scope", ["query:read", "experiment:read"], True, 200),
            ("no_filter_needs_no_experiment_scope", ["query:read"], False, 200),
        ]
    )
    def test_query_endpoint_scope_parity_for_api_keys(
        self, _name: str, scopes: list[str], with_filter: bool, expected_status: int
    ) -> None:
        experiment = self._create_experiment()
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        query: dict = {"kind": "RecordingsQuery"}
        if with_filter:
            query["experiment_exposure"] = {"experiment_id": experiment.id}

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": query},
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("replay_scope_only", ["session_recording:read"], True, 403),
            ("with_experiment_scope", ["session_recording:read", "experiment:read"], True, 200),
            ("no_filter_needs_no_experiment_scope", ["session_recording:read"], False, 200),
        ]
    )
    def test_list_endpoint_scope_parity_for_api_keys(
        self, _name: str, scopes: list[str], with_filter: bool, expected_status: int
    ) -> None:
        experiment = self._create_experiment()
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        params = {"experiment_exposure": json.dumps({"experiment_id": experiment.id})} if with_filter else {}

        response = self.client.get(
            f"/api/projects/{self.team.pk}/session_recordings/",
            params,
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.content

    @parameterized.expand(
        [
            ("playlist_scope_only", ["session_recording_playlist:read"], True, 403),
            ("with_experiment_scope", ["session_recording_playlist:read", "experiment:read"], True, 200),
            ("no_filter_needs_no_experiment_scope", ["session_recording_playlist:read"], False, 200),
        ]
    )
    def test_playlist_recordings_endpoint_scope_parity_for_api_keys(
        self, _name: str, scopes: list[str], with_filter: bool, expected_status: int
    ) -> None:
        # A filters playlist's recordings action parses the same query params into a
        # RecordingsQuery as the recordings list, so without the conditional scope a
        # playlist-read token could read which recordings belong to an experiment's
        # exposed population, per variant.
        experiment = self._create_experiment()
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team, created_by=self.user, type=SessionRecordingPlaylist.PlaylistType.FILTERS
        )
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        params = {"experiment_exposure": json.dumps({"experiment_id": experiment.id})} if with_filter else {}

        response = self.client.get(
            f"/api/projects/{self.team.pk}/session_recording_playlists/{playlist.short_id}/recordings",
            params,
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.content
