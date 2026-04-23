from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Request, Session

from posthog.temporal.data_imports.sources.salesforce.salesforce import (
    SalesforceEndpointPaginator,
    SalesforceResumeConfig,
    salesforce_source,
)

INSTANCE_URL = "https://example.my.salesforce.com"
QUERY_PATH = "/services/data/v61.0/query"


def _mock_response(records: list[dict[str, Any]]) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = {"records": records}
    return response


def _mock_empty_response() -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = {"records": []}
    return response


def _two_records(model: str = "Account") -> list[dict[str, Any]]:
    return [
        {"Id": "001A0", "attributes": {"type": model}},
        {"Id": "001B9", "attributes": {"type": model}},
    ]


class TestSalesforceEndpointPaginator:
    def test_update_state_populates_cursor(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.update_state(_mock_response(_two_records()))

        assert paginator.has_next_page is True
        assert paginator._last_record_id == "001B9"
        assert paginator._model_name == "Account"

    def test_update_state_empty_page_terminates(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.update_state(_mock_empty_response())

        assert paginator.has_next_page is False

    def test_update_request_non_incremental_replaces_query_param(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.update_state(_mock_response(_two_records("Lead")))

        request = Request(method="GET", url=f"{INSTANCE_URL}{QUERY_PATH}", params={"q": "irrelevant"})
        paginator.update_request(request)

        assert request.url == f"{INSTANCE_URL}{QUERY_PATH}"
        assert request.params == {
            "q": "SELECT FIELDS(ALL) FROM Lead WHERE Id > '001B9' ORDER BY Id ASC LIMIT 200",
        }

    def test_update_request_incremental_caches_date_filter(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=True)
        paginator.update_state(_mock_response(_two_records("Account")))

        initial_query = (
            "SELECT FIELDS(ALL) FROM Account WHERE SystemModstamp >= 2024-01-01T00:00:00.000+0000 "
            "ORDER BY Id ASC LIMIT 200"
        )
        request = Request(method="GET", url=f"{INSTANCE_URL}{QUERY_PATH}", params={"q": initial_query})
        paginator.update_request(request)

        assert paginator._date_filter == "2024-01-01T00:00:00.000+0000"
        assert request.params == {
            "q": (
                "SELECT FIELDS(ALL) FROM Account WHERE Id > '001B9' "
                "AND SystemModstamp >= 2024-01-01T00:00:00.000+0000 ORDER BY Id ASC LIMIT 200"
            ),
        }

    def test_update_request_incremental_without_date_filter_raises(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=True)
        paginator.update_state(_mock_response(_two_records("Account")))

        request = Request(
            method="GET",
            url=f"{INSTANCE_URL}{QUERY_PATH}",
            params={"q": "SELECT FIELDS(ALL) FROM Account ORDER BY Id ASC LIMIT 200"},
        )

        with pytest.raises(ValueError, match="No date filter found"):
            paginator.update_request(request)

    def test_update_request_no_op_when_no_next_page(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.update_state(_mock_empty_response())

        request = Request(method="GET", url=f"{INSTANCE_URL}{QUERY_PATH}", params={"q": "anything"})
        paginator.update_request(request)

        assert request.url == f"{INSTANCE_URL}{QUERY_PATH}"
        assert request.params == {"q": "anything"}

    def test_prepared_request_has_single_q_param_after_pagination(self) -> None:
        # Guards against the duplicate-``q`` regression: ``requests`` merges a query
        # string on the URL with ``request.params`` when preparing, so the paginator
        # must only mutate ``params`` — never the URL.
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.update_state(_mock_response(_two_records("Lead")))

        request = Request(
            method="GET",
            url=f"{INSTANCE_URL}{QUERY_PATH}",
            params={"q": "SELECT FIELDS(ALL) FROM Lead ORDER BY Id ASC LIMIT 200"},
        )
        paginator.update_request(request)

        prepared = Session().prepare_request(request)
        assert prepared.url is not None
        assert prepared.url.count("q=") == 1
        assert "Id+%3E+%27001B9%27" in prepared.url

    @parameterized.expand(
        [
            ("fresh_paginator", False, False, None, None),
            (
                "after_update_non_incremental",
                False,
                True,
                None,
                {"model_name": "Account", "last_record_id": "001B9"},
            ),
            ("incremental_without_date_filter_not_safe", True, True, None, None),
            (
                "incremental_with_date_filter",
                True,
                True,
                "2024-01-01T00:00:00.000+0000",
                {
                    "model_name": "Account",
                    "last_record_id": "001B9",
                    "date_filter": "2024-01-01T00:00:00.000+0000",
                },
            ),
        ]
    )
    def test_get_resume_state(
        self,
        _name: str,
        incremental: bool,
        advance: bool,
        date_filter: Optional[str],
        expected: Optional[dict[str, Any]],
    ) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=incremental)
        if advance:
            paginator.update_state(_mock_response(_two_records("Account")))
        if date_filter is not None:
            paginator._date_filter = date_filter

        assert paginator.get_resume_state() == expected

    def test_set_resume_state_round_trip(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=True)
        paginator.set_resume_state(
            {
                "model_name": "Lead",
                "last_record_id": "00QXYZ",
                "date_filter": "2024-01-01T00:00:00.000+0000",
            }
        )

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {
            "model_name": "Lead",
            "last_record_id": "00QXYZ",
            "date_filter": "2024-01-01T00:00:00.000+0000",
        }

    def test_init_request_raises_when_resumed_incremental_state_lacks_date_filter(self) -> None:
        # Guards against stale resume state written by an older version that omits
        # ``date_filter`` — resuming without it would silently drop the
        # ``SystemModstamp`` predicate and over-fetch records.
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=True)
        paginator.set_resume_state({"model_name": "Lead", "last_record_id": "00QXYZ"})

        request = Request(method="GET", url=f"{INSTANCE_URL}{QUERY_PATH}", params={"q": "initial"})

        with pytest.raises(ValueError, match="date_filter is required"):
            paginator.init_request(request)

    def test_set_resume_state_ignores_incomplete(self) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        paginator.set_resume_state({"model_name": "Lead"})

        assert paginator._model_name is None
        assert paginator._last_record_id is None
        assert paginator.get_resume_state() is None

    @parameterized.expand(
        [
            ("fresh_run", False),
            ("seeded_run", True),
        ]
    )
    def test_init_request(self, _name: str, seed: bool) -> None:
        paginator = SalesforceEndpointPaginator(should_use_incremental_field=False)
        request = Request(method="GET", url=f"{INSTANCE_URL}{QUERY_PATH}", params={"q": "initial"})

        if seed:
            paginator.set_resume_state({"model_name": "Lead", "last_record_id": "00QXYZ"})

        paginator.init_request(request)

        assert request.url == f"{INSTANCE_URL}{QUERY_PATH}"
        if seed:
            assert request.params == {
                "q": "SELECT FIELDS(ALL) FROM Lead WHERE Id > '00QXYZ' ORDER BY Id ASC LIMIT 200",
            }
        else:
            assert request.params == {"q": "initial"}


class TestSalesforceSourceResumeWiring:
    def _build_manager(self, can_resume: bool, loaded: Optional[SalesforceResumeConfig]) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = loaded
        return manager

    @mock.patch("posthog.temporal.data_imports.sources.salesforce.salesforce.rest_api_resource")
    def test_fresh_run_does_not_seed_paginator(self, mock_rest: mock.MagicMock) -> None:
        manager = self._build_manager(can_resume=False, loaded=None)

        salesforce_source(
            instance_url=INSTANCE_URL,
            access_token="token",
            refresh_token="refresh",
            endpoint="Account",
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
        )

        _args, kwargs = mock_rest.call_args
        assert kwargs["initial_paginator_state"] is None
        manager.load_state.assert_not_called()

    @mock.patch("posthog.temporal.data_imports.sources.salesforce.salesforce.rest_api_resource")
    def test_resume_run_seeds_paginator_from_saved_state(self, mock_rest: mock.MagicMock) -> None:
        loaded = SalesforceResumeConfig(
            model_name="Account",
            last_record_id="001ZZZ",
            date_filter="2024-01-01T00:00:00.000+0000",
        )
        manager = self._build_manager(can_resume=True, loaded=loaded)

        salesforce_source(
            instance_url=INSTANCE_URL,
            access_token="token",
            refresh_token="refresh",
            endpoint="Account",
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
        )

        _args, kwargs = mock_rest.call_args
        assert kwargs["initial_paginator_state"] == {
            "model_name": "Account",
            "last_record_id": "001ZZZ",
            "date_filter": "2024-01-01T00:00:00.000+0000",
        }

    @mock.patch("posthog.temporal.data_imports.sources.salesforce.salesforce.rest_api_resource")
    def test_resume_hook_persists_checkpoint(self, mock_rest: mock.MagicMock) -> None:
        manager = self._build_manager(can_resume=False, loaded=None)

        salesforce_source(
            instance_url=INSTANCE_URL,
            access_token="token",
            refresh_token="refresh",
            endpoint="Account",
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
        )

        _args, kwargs = mock_rest.call_args
        resume_hook = kwargs["resume_hook"]

        resume_hook(
            {
                "model_name": "Account",
                "last_record_id": "001ZZZ",
                "date_filter": "2024-01-01T00:00:00.000+0000",
            }
        )
        manager.save_state.assert_called_once_with(
            SalesforceResumeConfig(
                model_name="Account",
                last_record_id="001ZZZ",
                date_filter="2024-01-01T00:00:00.000+0000",
            )
        )

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

        resume_hook({"model_name": "Account"})
        manager.save_state.assert_not_called()
