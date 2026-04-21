from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.mailchimp.mailchimp import (
    MailchimpPaginator,
    MailchimpResumeConfig,
    _fetch_contacts_for_list,
    _format_incremental_value,
    _get_contacts_iterator,
    extract_data_center,
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
        monkeypatch.setattr("posthog.temporal.data_imports.sources.mailchimp.mailchimp.requests.get", get_mock)

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


class TestGetContactsIterator:
    def test_fresh_run_iterates_all_lists_and_saves_state(self, monkeypatch):
        manager = _fake_manager(can_resume=False)
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp._fetch_all_lists",
            lambda api_key, dc: [{"id": "list_a"}, {"id": "list_b"}],
        )
        responses_by_list = {
            "list_a": [_build_response([{"id": "a1"}], total_items=1)],
            "list_b": [_build_response([{"id": "b1"}], total_items=1)],
        }

        def fake_get(url, **kwargs):
            for list_id, pages in responses_by_list.items():
                if f"/lists/{list_id}/members" in url:
                    return pages.pop(0)
            raise AssertionError(f"unexpected url={url}")

        monkeypatch.setattr("posthog.temporal.data_imports.sources.mailchimp.mailchimp.requests.get", fake_get)

        emitted = list(_get_contacts_iterator(api_key="key-us6", resumable_source_manager=manager))

        assert [(c["list_id"], c["id"]) for c in emitted] == [
            ("list_a", "a1"),
            ("list_b", "b1"),
        ]
        # One checkpoint per list's first (and only) page.
        assert manager.save_state.call_args_list == [
            ((MailchimpResumeConfig(list_id="list_a", offset=0),),),
            ((MailchimpResumeConfig(list_id="list_b", offset=0),),),
        ]
        manager.load_state.assert_not_called()

    def test_resume_skips_prior_lists_and_starts_from_saved_offset(self, monkeypatch):
        manager = _fake_manager(
            can_resume=True,
            load_state=MailchimpResumeConfig(list_id="list_b", offset=1000),
        )
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp._fetch_all_lists",
            lambda api_key, dc: [{"id": "list_a"}, {"id": "list_b"}, {"id": "list_c"}],
        )
        visited: list[tuple[str, int]] = []

        def fake_get(url, **kwargs):
            offset = kwargs["params"]["offset"]
            if "/lists/list_b/members" in url:
                visited.append(("list_b", offset))
                if offset == 1000:
                    return _build_response([{"id": "b2"}], total_items=1001)
                return _build_response([], total_items=1001)
            if "/lists/list_c/members" in url:
                visited.append(("list_c", offset))
                if offset == 0:
                    return _build_response([{"id": "c1"}], total_items=1)
                return _build_response([], total_items=1)
            raise AssertionError(f"unexpected url={url} — list_a must be skipped on resume")

        monkeypatch.setattr("posthog.temporal.data_imports.sources.mailchimp.mailchimp.requests.get", fake_get)

        emitted = list(_get_contacts_iterator(api_key="key-us6", resumable_source_manager=manager))

        assert [(c["list_id"], c["id"]) for c in emitted] == [
            ("list_b", "b2"),
            ("list_c", "c1"),
        ]
        assert visited == [("list_b", 1000), ("list_c", 0)]

    def test_resume_falls_back_to_fresh_when_list_id_missing(self, monkeypatch):
        manager = _fake_manager(
            can_resume=True,
            load_state=MailchimpResumeConfig(list_id="gone", offset=500),
        )
        monkeypatch.setattr(
            "posthog.temporal.data_imports.sources.mailchimp.mailchimp._fetch_all_lists",
            lambda api_key, dc: [{"id": "list_a"}],
        )

        def fake_get(url, **kwargs):
            assert kwargs["params"]["offset"] == 0, "must start from scratch when list_id is gone"
            return _build_response([{"id": "a1"}], total_items=1)

        monkeypatch.setattr("posthog.temporal.data_imports.sources.mailchimp.mailchimp.requests.get", fake_get)

        emitted = list(_get_contacts_iterator(api_key="key-us6", resumable_source_manager=manager))

        assert [(c["list_id"], c["id"]) for c in emitted] == [("list_a", "a1")]
