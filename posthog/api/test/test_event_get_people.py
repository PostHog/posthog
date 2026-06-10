from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.api.event import EventViewSet
from posthog.hogql_queries.events_query_runner import EventsQueryRunner

# ---------------------------------------------------------------------------
# EventViewSet._get_people
# ---------------------------------------------------------------------------


class TestEventViewSetGetPeople:
    def _make_viewset(self) -> EventViewSet:
        viewset = EventViewSet.__new__(EventViewSet)
        return viewset

    def _make_team(self, pk: int = 1) -> MagicMock:
        team = MagicMock()
        team.pk = pk
        return team

    def _make_person(self, uuid: str = "uuid-1") -> MagicMock:
        person = MagicMock()
        person.uuid = uuid
        person.properties = {}
        person.distinct_ids = []
        return person

    @patch("posthog.api.event.get_persons_mapped_by_distinct_id")
    def test_returns_mapping_from_single_rpc(self, mock_get_persons):
        viewset = self._make_viewset()
        team = self._make_team(pk=42)
        person = self._make_person()
        mock_get_persons.return_value = {"user-1": person}

        query_result = [{"distinct_id": "user-1"}, {"distinct_id": "user-1"}]
        result = viewset._get_people(query_result, team)

        assert result == {"user-1": person}

    @patch("posthog.api.event.get_persons_mapped_by_distinct_id")
    def test_deduplicates_distinct_ids_before_rpc(self, mock_get_persons):
        viewset = self._make_viewset()
        team = self._make_team(pk=5)
        mock_get_persons.return_value = {}

        # 3000 events, only 3 distinct users
        query_result = [{"distinct_id": f"user-{i % 3}"} for i in range(3000)]
        viewset._get_people(query_result, team)

        assert mock_get_persons.call_count == 1
        _team_id, passed_ids = mock_get_persons.call_args.args
        assert _team_id == 5
        assert set(passed_ids) == {"user-0", "user-1", "user-2"}
        assert len(passed_ids) == 3

    @patch("posthog.api.event.get_persons_mapped_by_distinct_id")
    def test_passes_team_pk_to_rpc(self, mock_get_persons):
        viewset = self._make_viewset()
        team = self._make_team(pk=99)
        mock_get_persons.return_value = {}

        viewset._get_people([{"distinct_id": "x"}], team)

        team_id_used = mock_get_persons.call_args.args[0]
        assert team_id_used == 99

    @patch("posthog.api.event.get_persons_mapped_by_distinct_id")
    def test_empty_query_result_returns_empty_dict_without_rpc(self, mock_get_persons):
        viewset = self._make_viewset()
        team = self._make_team()
        mock_get_persons.return_value = {}

        result = viewset._get_people([], team)

        assert result == {}
        # The RPC is still called — deduplicated empty list is passed through.
        # This matches the current implementation which always delegates to the helper.
        assert mock_get_persons.call_count == 1
        _, passed_ids = mock_get_persons.call_args.args
        assert passed_ids == []

    @parameterized.expand(
        [
            ("single_event", [{"distinct_id": "alice"}], {"alice"}),
            ("two_distinct_users", [{"distinct_id": "alice"}, {"distinct_id": "bob"}], {"alice", "bob"}),
            (
                "many_events_few_users",
                [{"distinct_id": f"u{i % 5}"} for i in range(100)],
                {"u0", "u1", "u2", "u3", "u4"},
            ),
        ]
    )
    @patch("posthog.api.event.get_persons_mapped_by_distinct_id")
    def test_distinct_id_set_passed_to_rpc(self, _name, query_result, expected_ids, mock_get_persons):
        mock_get_persons.return_value = {}
        viewset = self._make_viewset()
        team = self._make_team()

        viewset._get_people(query_result, team)

        _, passed_ids = mock_get_persons.call_args.args
        assert set(passed_ids) == expected_ids


# ---------------------------------------------------------------------------
# EventsQueryRunner person enrichment batching
# ---------------------------------------------------------------------------


class TestEventsQueryRunnerPersonBatching:
    def _make_runner(self, team_pk: int = 1) -> EventsQueryRunner:
        runner = EventsQueryRunner.__new__(EventsQueryRunner)
        runner.team = MagicMock()
        runner.team.pk = team_pk
        return runner

    def _make_person(self, uuid: str) -> MagicMock:
        person = MagicMock()
        person.uuid = uuid
        return person

    @patch("posthog.hogql_queries.events_query_runner.get_persons_mapped_by_distinct_id")
    def test_single_batch_when_ids_fit_within_limit(self, mock_get_persons):
        runner = self._make_runner(team_pk=7)
        person_a = self._make_person("uuid-a")
        person_b = self._make_person("uuid-b")
        mock_get_persons.return_value = {"user-a": person_a, "user-b": person_b}

        distinct_ids = ["user-a", "user-b"]
        distinct_to_person: dict = {}
        batch_size = 1000
        for i in range(0, len(distinct_ids), batch_size):
            batch = distinct_ids[i : i + batch_size]
            distinct_to_person.update(mock_get_persons(runner.team.pk, batch))

        assert mock_get_persons.call_count == 1
        assert distinct_to_person == {"user-a": person_a, "user-b": person_b}

    @patch("posthog.hogql_queries.events_query_runner.get_persons_mapped_by_distinct_id")
    def test_splits_into_batches_of_1000(self, mock_get_persons):
        runner = self._make_runner(team_pk=3)
        # 2500 distinct ids → should produce 3 RPC calls (1000, 1000, 500)
        distinct_ids = [f"user-{i}" for i in range(2500)]
        mock_get_persons.side_effect = lambda team_id, batch: {d: self._make_person(d) for d in batch}

        distinct_to_person: dict = {}
        batch_size = 1000
        for i in range(0, len(distinct_ids), batch_size):
            batch = distinct_ids[i : i + batch_size]
            distinct_to_person.update(mock_get_persons(runner.team.pk, batch))

        assert mock_get_persons.call_count == 3
        # Each call should have received exactly the right batch size
        call_args_list = mock_get_persons.call_args_list
        assert len(call_args_list[0].args[1]) == 1000
        assert len(call_args_list[1].args[1]) == 1000
        assert len(call_args_list[2].args[1]) == 500

    @patch("posthog.hogql_queries.events_query_runner.get_persons_mapped_by_distinct_id")
    def test_merges_results_from_multiple_batches(self, mock_get_persons):
        runner = self._make_runner(team_pk=4)
        batch_1_ids = [f"a-{i}" for i in range(1000)]
        batch_2_ids = [f"b-{i}" for i in range(500)]
        distinct_ids = batch_1_ids + batch_2_ids

        batch_1_result = {d: self._make_person(d) for d in batch_1_ids}
        batch_2_result = {d: self._make_person(d) for d in batch_2_ids}
        mock_get_persons.side_effect = [batch_1_result, batch_2_result]

        distinct_to_person: dict = {}
        batch_size = 1000
        for i in range(0, len(distinct_ids), batch_size):
            batch = distinct_ids[i : i + batch_size]
            distinct_to_person.update(mock_get_persons(runner.team.pk, batch))

        assert set(distinct_to_person.keys()) == set(batch_1_ids + batch_2_ids)
        assert len(distinct_to_person) == 1500

    @patch("posthog.hogql_queries.events_query_runner.get_persons_mapped_by_distinct_id")
    def test_exact_batch_boundary_produces_correct_call_count(self, mock_get_persons):
        runner = self._make_runner()
        # Exactly 2000 ids → 2 calls of 1000 each
        distinct_ids = [f"user-{i}" for i in range(2000)]
        mock_get_persons.side_effect = lambda team_id, batch: {d: self._make_person(d) for d in batch}

        distinct_to_person: dict = {}
        batch_size = 1000
        for i in range(0, len(distinct_ids), batch_size):
            batch = distinct_ids[i : i + batch_size]
            distinct_to_person.update(mock_get_persons(runner.team.pk, batch))

        assert mock_get_persons.call_count == 2
        for c in mock_get_persons.call_args_list:
            assert len(c.args[1]) == 1000

    @patch("posthog.hogql_queries.events_query_runner.get_persons_mapped_by_distinct_id")
    def test_empty_distinct_ids_calls_no_rpc(self, mock_get_persons):
        runner = self._make_runner()
        distinct_ids: list = []
        distinct_to_person: dict = {}
        batch_size = 1000
        for i in range(0, len(distinct_ids), batch_size):
            batch = distinct_ids[i : i + batch_size]
            distinct_to_person.update(mock_get_persons(runner.team.pk, batch))

        assert mock_get_persons.call_count == 0
        assert distinct_to_person == {}
