import json
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Request, Response

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.zendesk.zendesk import (
    ResumableJSONLinkPaginator,
    ZendeskIncrementalEndpointPaginator,
    ZendeskResumeConfig,
    ZendeskTicketsIncrementalEndpointPaginator,
    zendesk_source,
)


def _make_response(json_body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestResumableJSONLinkPaginator:
    def test_get_resume_state_initial(self) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        assert paginator.get_resume_state() is None

    def test_get_resume_state_after_update_with_next_url(self) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        response = MagicMock()
        response.json.return_value = {"links": {"next": "https://sub.zendesk.com/api/v2/users?page=2"}}
        paginator.update_state(response)

        assert paginator.get_resume_state() == {"next_url": "https://sub.zendesk.com/api/v2/users?page=2"}

    def test_get_resume_state_on_terminal_page(self) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        response = MagicMock()
        response.json.return_value = {"links": {"next": None}}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        paginator.set_resume_state({"next_url": "https://sub.zendesk.com/api/v2/users?page=5"})

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_url": "https://sub.zendesk.com/api/v2/users?page=5"}

    @parameterized.expand(
        [
            ("no_seed", None),
            ("seeded", "https://sub.zendesk.com/api/v2/users?page=3"),
        ]
    )
    def test_init_request(self, _name: str, seed_url: Optional[str]) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        if seed_url is not None:
            paginator.set_resume_state({"next_url": seed_url})

        request = Request(method="GET", url="https://sub.zendesk.com/api/v2/users")
        paginator.init_request(request)

        assert request.url == (seed_url if seed_url is not None else "https://sub.zendesk.com/api/v2/users")

    def test_set_resume_state_ignores_missing_next_url(self) -> None:
        paginator = ResumableJSONLinkPaginator(next_url_path="links.next")
        paginator.set_resume_state({})

        assert paginator.get_resume_state() is None


class TestZendeskTicketsIncrementalEndpointPaginator:
    def test_update_state_mid_stream(self) -> None:
        paginator = ZendeskTicketsIncrementalEndpointPaginator()
        response = MagicMock()
        response.json.return_value = {
            "end_of_stream": False,
            "tickets": [{"generated_timestamp": 1234567890}],
        }
        paginator.update_state(response)

        assert paginator._has_next_page is True
        assert paginator._next_start_time == 1234567890
        assert paginator.get_resume_state() == {"next_start_time": 1234567890}

    def test_update_state_end_of_stream(self) -> None:
        paginator = ZendeskTicketsIncrementalEndpointPaginator()
        response = MagicMock()
        response.json.return_value = {"end_of_stream": True, "tickets": []}
        paginator.update_state(response)

        assert paginator._has_next_page is False
        assert paginator._next_start_time is None
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ZendeskTicketsIncrementalEndpointPaginator()
        paginator.set_resume_state({"next_start_time": 42})

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_start_time": 42}

    def test_init_request_seeded_overrides_start_time_param(self) -> None:
        paginator = ZendeskTicketsIncrementalEndpointPaginator()
        paginator.set_resume_state({"next_start_time": 42})

        # The rest framework seeds the incremental ``start_time`` param on its
        # own before ``init_request`` runs — verify resume overrides it.
        request = Request(
            method="GET",
            url="https://sub.zendesk.com/api/v2/incremental/tickets",
            params={"start_time": 0, "per_page": 1000},
        )
        paginator.init_request(request)

        assert request.params["start_time"] == 42
        assert request.params["per_page"] == 1000

    def test_init_request_fresh_leaves_params_untouched(self) -> None:
        paginator = ZendeskTicketsIncrementalEndpointPaginator()

        request = Request(
            method="GET",
            url="https://sub.zendesk.com/api/v2/incremental/tickets",
            params={"start_time": 0, "per_page": 1000},
        )
        paginator.init_request(request)

        assert request.params["start_time"] == 0


class TestZendeskIncrementalEndpointPaginator:
    def test_update_state_mid_stream(self) -> None:
        paginator = ZendeskIncrementalEndpointPaginator()
        response = MagicMock()
        response.json.return_value = {
            "end_of_stream": False,
            "next_page": "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=123",
        }
        paginator.update_state(response)

        assert paginator._has_next_page is True
        assert paginator.get_resume_state() == {
            "next_url": "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=123"
        }

    def test_update_state_end_of_stream(self) -> None:
        paginator = ZendeskIncrementalEndpointPaginator()
        response = MagicMock()
        response.json.return_value = {"end_of_stream": True}
        paginator.update_state(response)

        assert paginator._has_next_page is False
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ZendeskIncrementalEndpointPaginator()
        paginator.set_resume_state(
            {"next_url": "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=999"}
        )

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {
            "next_url": "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=999"
        }

    def test_init_request_seeded_overrides_url(self) -> None:
        paginator = ZendeskIncrementalEndpointPaginator()
        paginator.set_resume_state(
            {"next_url": "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=999"}
        )

        request = Request(
            method="GET",
            url="https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=0",
        )
        paginator.init_request(request)

        assert request.url == "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=999"

    def test_init_request_fresh_leaves_url_untouched(self) -> None:
        paginator = ZendeskIncrementalEndpointPaginator()

        original_url = "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=0"
        request = Request(method="GET", url=original_url)
        paginator.init_request(request)

        assert request.url == original_url


class TestZendeskResumeConfigSerialization:
    def test_url_shape_round_trip(self) -> None:
        import dataclasses

        cfg = ZendeskResumeConfig(next_url="https://sub.zendesk.com/api/v2/users?page=2")
        reconstituted = ZendeskResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
        assert reconstituted.next_start_time is None

    def test_cursor_shape_round_trip(self) -> None:
        import dataclasses

        cfg = ZendeskResumeConfig(next_start_time=1234567890)
        reconstituted = ZendeskResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
        assert reconstituted.next_url is None


class TestZendeskSourceEndToEnd:
    """End-to-end resume behaviour of ``zendesk_source`` with a mocked HTTP
    session. Uses the ``users`` endpoint to exercise the URL-based
    ``ResumableJSONLinkPaginator`` path, and ``tickets`` to exercise the
    ``start_time`` cursor path."""

    subdomain = "sub"
    api_key = "key"
    email_address = "a@b.com"
    team_id = 123
    job_id = "test_job"

    def _run_endpoint(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
    ) -> tuple[list[Optional[str]], list[dict[str, Any]]]:
        """Drive ``zendesk_source`` with a mocked HTTP session.

        Returns ``(sent_urls, sent_params)`` captured at send-time — the
        underlying ``Request`` object is mutated in-place by the paginator
        between pages, so we can't rely on ``mock.call_args_list`` to
        preserve history.
        """
        sent_urls: list[Optional[str]] = []
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            sent_params.append(dict(request.params) if request.params else {})
            return next(response_iter)

        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = zendesk_source(
                subdomain=self.subdomain,
                api_key=self.api_key,
                email_address=self.email_address,
                endpoint=endpoint,
                team_id=self.team_id,
                job_id=self.job_id,
                db_incremental_field_last_value=None,
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
            )
            # Drain the resource to exercise the pagination loop.
            list(resource)
            return sent_urls, sent_params

    def test_users_fresh_run_saves_next_url_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"users": [{"id": 1}], "links": {"next": "https://sub.zendesk.com/api/v2/users?page=2"}}),
            _make_response({"users": [{"id": 2}], "links": {"next": None}}),
        ]
        self._run_endpoint("users", manager, responses)

        # Only the non-terminal page produces a checkpoint.
        save_calls = manager.save_state.call_args_list
        assert len(save_calls) == 1
        saved = save_calls[0].args[0]
        assert isinstance(saved, ZendeskResumeConfig)
        assert saved.next_url == "https://sub.zendesk.com/api/v2/users?page=2"
        assert saved.next_start_time is None

    def test_users_resume_seeds_paginator_with_saved_next_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZendeskResumeConfig(next_url="https://sub.zendesk.com/api/v2/users?page=7")

        responses = [
            _make_response({"users": [{"id": 7}], "links": {"next": None}}),
        ]
        sent_urls, _ = self._run_endpoint("users", manager, responses)

        assert sent_urls[0] == "https://sub.zendesk.com/api/v2/users?page=7"

    def test_users_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"users": [{"id": 1}], "links": {"next": None}}),
        ]
        self._run_endpoint("users", manager, responses)

        manager.save_state.assert_not_called()

    def test_users_empty_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"users": [], "links": {"next": None}}),
        ]
        self._run_endpoint("users", manager, responses)

        manager.save_state.assert_not_called()

    def test_tickets_fresh_run_saves_next_start_time(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_response({"tickets": [{"id": 1, "generated_timestamp": 1000}], "end_of_stream": False}),
            _make_response({"tickets": [{"id": 2, "generated_timestamp": 2000}], "end_of_stream": True}),
        ]
        self._run_endpoint("tickets", manager, responses, should_use_incremental_field=True)

        save_calls = manager.save_state.call_args_list
        assert len(save_calls) == 1
        saved = save_calls[0].args[0]
        assert isinstance(saved, ZendeskResumeConfig)
        assert saved.next_start_time == 1000
        assert saved.next_url is None

    def test_tickets_resume_uses_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZendeskResumeConfig(next_start_time=5000)

        responses = [
            _make_response({"tickets": [{"id": 99, "generated_timestamp": 6000}], "end_of_stream": True}),
        ]
        _, sent_params = self._run_endpoint("tickets", manager, responses, should_use_incremental_field=True)

        assert sent_params[0]["start_time"] == 5000

    def test_ticket_events_resume_uses_saved_next_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZendeskResumeConfig(
            next_url="https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=9999"
        )

        responses = [
            _make_response({"ticket_events": [{"id": 1}], "end_of_stream": True}),
        ]
        sent_urls, _ = self._run_endpoint("ticket_events", manager, responses)

        assert sent_urls[0] == "https://sub.zendesk.com/api/v2/incremental/ticket_events?start_time=9999"

    def test_users_resume_with_mismatched_shape_falls_back_to_fresh(self) -> None:
        # A saved ``next_start_time`` can't seed a URL-based paginator — the
        # loader ignores it and the fresh path is used instead.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZendeskResumeConfig(next_start_time=1234)

        responses = [
            _make_response({"users": [{"id": 1}], "links": {"next": None}}),
        ]
        sent_urls, sent_params = self._run_endpoint("users", manager, responses)

        # No seeded URL — first request still hits the initial path.
        assert "/api/v2/users" in (sent_urls[0] or "")
        assert "start_time" not in sent_params[0]
