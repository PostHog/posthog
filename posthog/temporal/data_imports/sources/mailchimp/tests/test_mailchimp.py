import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.mailchimp.mailchimp import (
    MailchimpPaginator,
    MailchimpResumeConfig,
    _fetch_contacts_for_list,
    _format_incremental_value,
    _get_contacts_iterator,
    extract_data_center,
    mailchimp_source,
)


class TestExtractDataCenter:
    def test_basic_key(self):
        assert extract_data_center("abc123def456-us6") == "us6"

    def test_multiple_dashes(self):
        assert extract_data_center("abc-def-ghi-us10") == "us10"

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center("invalidkey")

    @pytest.mark.parametrize(
        "malicious_key",
        [
            "key-evil.com/#",
            "key-evil.com/path",
            "key-us6.attacker.com",
            "key-dc:8080",
            "key-",
            "key- spaces",
        ],
    )
    def test_malicious_dc_values_raise(self, malicious_key):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center(malicious_key)


class TestFormatIncrementalValue:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 45)
        result = _format_incremental_value(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_date(self):
        d = date(2024, 1, 15)
        result = _format_incremental_value(d)
        assert result == "2024-01-15T00:00:00+00:00"

    def test_string(self):
        assert _format_incremental_value("2024-01-15") == "2024-01-15"


class TestMailchimpPaginator:
    def test_initial_state(self):
        paginator = MailchimpPaginator(page_size=100)
        assert paginator._page_size == 100
        assert paginator._offset == 0

    def test_update_state_has_more(self):
        paginator = MailchimpPaginator(page_size=100)
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 100
        assert paginator._has_next_page is True

    def test_update_state_no_more(self):
        paginator = MailchimpPaginator(page_size=100)
        paginator._offset = 200
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 300
        assert paginator._has_next_page is False

    @pytest.mark.parametrize(
        ("label", "seeded_offset"),
        [
            ("fresh", None),
            ("resumed", 2000),
        ],
    )
    def test_init_request_sets_offset_and_count(self, label: str, seeded_offset: int | None) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        if seeded_offset is not None:
            paginator.set_resume_state({"offset": seeded_offset})

        request = Request(method="GET", url="https://us6.api.mailchimp.com/3.0/lists")
        paginator.init_request(request)

        assert request.params["count"] == 1000
        assert request.params["offset"] == (seeded_offset if seeded_offset is not None else 0)

    def test_get_resume_state_returns_current_offset(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        response = MagicMock()
        response.json.return_value = {"total_items": 3000}
        paginator.update_state(response)  # _offset advances to 1000

        assert paginator.get_resume_state() == {"offset": 1000}

    def test_set_resume_state_round_trip(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        paginator.set_resume_state({"offset": 5000})

        assert paginator._offset == 5000
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"offset": 5000}

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = MailchimpPaginator(page_size=1000)
        paginator.set_resume_state({})

        assert paginator._offset == 0


def _fake_manager(*, can_resume: bool = False, load_state: MailchimpResumeConfig | None = None) -> MagicMock:
    """Build a ResumableSourceManager test double matching the protocol used by the loop."""
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = load_state
    return manager


def _build_response(members: list[dict[str, Any]], total_items: int) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"members": members, "total_items": total_items}
    response.raise_for_status.return_value = None
    return response


class TestFetchContactsForList:
    @pytest.mark.parametrize(
        ("label", "start_offset", "members", "total_items", "expected_ids", "expected_checkpoint"),
        [
            (
                "fresh_page_checkpoints_at_offset_zero",
                0,
                [{"id": "m1"}, {"id": "m2"}],
                2,
                ["m1", "m2"],
                MailchimpResumeConfig(list_id="list_a", offset=0),
            ),
            (
                "resume_page_checkpoints_at_start_offset",
                1000,
                [{"id": "m3"}],
                1001,
                ["m3"],
                MailchimpResumeConfig(list_id="list_a", offset=1000),
            ),
            (
                "empty_page_is_not_checkpointed",
                0,
                [],
                0,
                [],
                None,
            ),
        ],
    )
    def test_single_page_behaviour(
        self,
        monkeypatch,
        label: str,
        start_offset: int,
        members: list[dict[str, Any]],
        total_items: int,
        expected_ids: list[str],
        expected_checkpoint: MailchimpResumeConfig | None,
    ) -> None:
        manager = _fake_manager()
        get_mock = MagicMock(side_effect=[_build_response(members, total_items=total_items)])
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )

        emitted = list(
            _fetch_contacts_for_list(
                api_key="key-us6",
                dc="us6",
                list_id="list_a",
                since_last_changed=None,
                resumable_source_manager=manager,
                start_offset=start_offset,
            )
        )

        assert [c["id"] for c in emitted] == expected_ids
        assert all(c["list_id"] == "list_a" for c in emitted)
        assert get_mock.call_args.kwargs["params"]["offset"] == start_offset

        if expected_checkpoint is None:
            manager.save_state.assert_not_called()
        else:
            manager.save_state.assert_called_once_with(expected_checkpoint)

    def test_multi_page_advances_offset_and_checkpoints_each_page(self, monkeypatch) -> None:
        # total_items=2001 with page_size=1000 → pages at offsets 0, 1000, 2000.
        # After the third page, offset becomes 3000 and the `offset >= total_items` guard terminates the loop.
        manager = _fake_manager()
        responses = [_build_response([{"id": f"m{i}"}], total_items=2001) for i in range(3)]
        get_mock = MagicMock(side_effect=responses)
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(get_mock)})(),
        )

        emitted = list(
            _fetch_contacts_for_list(
                api_key="key-us6",
                dc="us6",
                list_id="list_a",
                since_last_changed=None,
                resumable_source_manager=manager,
                start_offset=0,
            )
        )

        assert [c["id"] for c in emitted] == ["m0", "m1", "m2"]
        assert [call.kwargs["params"]["offset"] for call in get_mock.call_args_list] == [0, 1000, 2000]
        assert manager.save_state.call_args_list == [
            ((MailchimpResumeConfig(list_id="list_a", offset=0),),),
            ((MailchimpResumeConfig(list_id="list_a", offset=1000),),),
            ((MailchimpResumeConfig(list_id="list_a", offset=2000),),),
        ]


class TestGetContactsIterator:
    @pytest.mark.parametrize(
        (
            "label",
            "can_resume",
            "load_state",
            "list_ids",
            "page_by_list_offset",
            "expected_emitted",
            "expected_visits",
            "expected_checkpoints",
            "load_state_called",
        ),
        [
            (
                "fresh_run_iterates_all_lists",
                False,
                None,
                ["list_a", "list_b"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                    ("list_b", 0): ([{"id": "b1"}], 1),
                },
                [("list_a", "a1"), ("list_b", "b1")],
                [("list_a", 0), ("list_b", 0)],
                [
                    MailchimpResumeConfig(list_id="list_a", offset=0),
                    MailchimpResumeConfig(list_id="list_b", offset=0),
                ],
                False,
            ),
            (
                "resume_skips_prior_lists_and_starts_mid_list",
                True,
                MailchimpResumeConfig(list_id="list_b", offset=1000),
                ["list_a", "list_b", "list_c"],
                {
                    ("list_b", 1000): ([{"id": "b2"}], 1001),
                    ("list_c", 0): ([{"id": "c1"}], 1),
                },
                [("list_b", "b2"), ("list_c", "c1")],
                [("list_b", 1000), ("list_c", 0)],
                [
                    MailchimpResumeConfig(list_id="list_b", offset=1000),
                    MailchimpResumeConfig(list_id="list_c", offset=0),
                ],
                True,
            ),
            (
                "resume_falls_back_to_fresh_when_list_id_missing",
                True,
                MailchimpResumeConfig(list_id="gone", offset=500),
                ["list_a"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                },
                [("list_a", "a1")],
                [("list_a", 0)],
                [MailchimpResumeConfig(list_id="list_a", offset=0)],
                True,
            ),
        ],
    )
    def test_iteration(
        self,
        monkeypatch,
        label: str,
        can_resume: bool,
        load_state: MailchimpResumeConfig | None,
        list_ids: list[str],
        page_by_list_offset: dict[tuple[str, int], tuple[list[dict[str, Any]], int]],
        expected_emitted: list[tuple[str, str]],
        expected_visits: list[tuple[str, int]],
        expected_checkpoints: list[MailchimpResumeConfig],
        load_state_called: bool,
    ) -> None:
        manager = _fake_manager(can_resume=can_resume, load_state=load_state)
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp._fetch_all_lists",
            lambda api_key, dc: [{"id": lid} for lid in list_ids],
        )
        visited: list[tuple[str, int]] = []

        def fake_get(url, **kwargs):
            offset = kwargs["params"]["offset"]
            for lid in list_ids:
                if f"/lists/{lid}/members" in url:
                    visited.append((lid, offset))
                    members, total_items = page_by_list_offset.get((lid, offset), ([], 0))
                    return _build_response(members, total_items=total_items)
            raise AssertionError(f"unexpected url={url}")

        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp.make_tracked_session",
            lambda *a, **k: type("_S", (), {"get": staticmethod(fake_get)})(),
        )

        emitted = list(_get_contacts_iterator(api_key="key-us6", resumable_source_manager=manager))

        assert [(c["list_id"], c["id"]) for c in emitted] == expected_emitted
        assert visited == expected_visits
        assert manager.save_state.call_args_list == [((cp,),) for cp in expected_checkpoints]
        if load_state_called:
            manager.load_state.assert_called_once()
        else:
            manager.load_state.assert_not_called()


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestRestEndpointResumeBehavior:
    """End-to-end resume behaviour of the shared ``rest_api_resource`` path used
    for ``lists``/``campaigns``/``reports`` (offset/count pagination)."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``mailchimp_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list
        of shallow copies of ``request.params`` captured at send-time — the
        underlying Request object is mutated in-place by the paginator between
        pages, so we can't rely on mock ``call_args_list`` to preserve history.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = mailchimp_source(
                api_key="key-us6",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            # SourceResponse.items is Iterable | AsyncIterable; the REST path is sync.
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        data_key = endpoint  # lists/campaigns/reports all use their own name as data_selector
        responses = [
            _make_http_response({data_key: [{"id": "a"}], "total_items": 2500}),
            _make_http_response({data_key: [{"id": "b"}], "total_items": 2500}),
            _make_http_response({data_key: [{"id": "c"}], "total_items": 2500}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        assert [p["offset"] for p in sent_params] == [0, 1000, 2000]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MailchimpResumeConfig(offset=1000),
            MailchimpResumeConfig(offset=2000),
        ]

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailchimpResumeConfig(offset=2000)

        data_key = endpoint
        responses = [
            _make_http_response({data_key: [{"id": "c"}], "total_items": 2500}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        assert [p["offset"] for p in sent_params] == [2000]

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_terminal_single_page_does_not_save_state(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        data_key = endpoint
        responses = [
            _make_http_response({data_key: [{"id": "only"}], "total_items": 1}),
        ]
        self._drive(endpoint, manager, responses)

        manager.save_state.assert_not_called()

    def test_saved_state_with_zero_offset_is_ignored(self) -> None:
        # A zero-offset checkpoint is equivalent to a fresh run — don't seed.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailchimpResumeConfig(offset=0)

        responses = [
            _make_http_response({"lists": [{"id": "a"}], "total_items": 1}),
        ]
        _, sent_params = self._drive("lists", manager, responses)

        assert [p["offset"] for p in sent_params] == [0]

    def test_saved_state_serialization_round_trip_with_list_id_absent(self) -> None:
        # REST-endpoint checkpoints omit list_id; ensure ResumableSourceManager's
        # asdict/json round trip reproduces the dataclass unchanged.
        import dataclasses

        cfg = MailchimpResumeConfig(offset=1500)
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = MailchimpResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg
        assert reconstituted.list_id is None
