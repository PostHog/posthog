from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PersonPropertyFilter, RecordingsQuery

from posthog.session_recordings.queries.recordings_query_runner import RecordingsQueryRunner
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.utils import expand_test_account_filters


class TestExpandTestAccountFilters(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("stray string", ["not-a-dict"]),
            ("stray int", [42]),
            ("stray None", [None]),
            ("mixed valid and invalid", [{"key": "email", "value": "@x", "type": "person"}, "not-a-dict"]),
        ]
    )
    def test_skips_non_dict_entries(self, _name: str, malformed: list) -> None:
        self.team.test_account_filters = malformed
        self.team.save()

        result = expand_test_account_filters(self.team)

        for entry in result:
            assert hasattr(entry, "type")

    def test_session_recording_list_from_query_survives_malformed_test_account_filters(self) -> None:
        self.team.test_account_filters = [
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
            "this-string-used-to-crash-the-listing",
        ]
        self.team.save()

        listing = SessionRecordingListFromQuery(
            team=self.team,
            query=RecordingsQuery(filter_test_accounts=True),
            hogql_query_modifiers=None,
        )

        result = listing.run()

        assert result.results == []
        assert any(isinstance(f, PersonPropertyFilter) for f in listing._test_account_filters)

    def test_recordings_query_runner_survives_malformed_test_account_filters(self) -> None:
        self.team.test_account_filters = [
            {"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"},
            ["nested", "list", "also", "invalid"],
        ]
        self.team.save()

        runner = RecordingsQueryRunner(query=RecordingsQuery(filter_test_accounts=True), team=self.team)

        response = runner.calculate()

        assert response.results == []
        assert response.has_next is False

    def test_only_valid_filters_are_expanded(self) -> None:
        self.team.test_account_filters = [
            {"key": "email", "value": "@x", "type": "person"},
            "stray",
            {"key": "$browser", "value": "Chrome", "type": "event"},
        ]
        self.team.save()

        result = expand_test_account_filters(self.team)

        assert len(result) == 2
        assert isinstance(result[0], PersonPropertyFilter)
        assert isinstance(result[1], EventPropertyFilter)
