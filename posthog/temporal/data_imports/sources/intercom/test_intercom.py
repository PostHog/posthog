import json
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import HTTPError, Response

from posthog.temporal.data_imports.sources.intercom.intercom import (
    INTERCOM_API_BASE,
    _company_segments_generator,
    _conversation_parts_generator,
)


def _make_response(body: Any, status_code: int = 200, url: str = "") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = url
    resp.reason = "Forbidden" if status_code == 403 else "OK"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_session(post_responses: list[Response], get_responses: dict[str, Response]) -> MagicMock:
    """Build a mock requests.Session.

    `post_responses` are returned in order — one per POST call (we only POST to
    `/conversations/search` or `/companies/list` from the substream generators).
    `get_responses` is keyed by URL so the per-row child fetches can be
    selectively forbidden.
    """
    session = MagicMock()
    post_iter = iter(post_responses)
    session.post.side_effect = lambda *args, **kwargs: next(post_iter)

    def fake_get(url: str, *args: Any, **kwargs: Any) -> Response:
        if url in get_responses:
            return get_responses[url]
        raise AssertionError(f"unexpected GET to {url}")

    session.get.side_effect = fake_get
    return session


class TestConversationPartsGenerator:
    """`_conversation_parts_generator` walks `POST /conversations/search` then
    fans out to `GET /conversations/{id}` per parent. A 403 on a single
    conversation must not abort the whole stream — see the misleading
    'missing scopes' classification at `source.py:34`."""

    def test_per_row_403_is_skipped_and_other_rows_still_yield(self) -> None:
        search_page = _make_response(
            {
                "conversations": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
                "pages": {"next": None},
            }
        )
        forbidden_url = f"{INTERCOM_API_BASE}/conversations/2"
        forbidden = _make_response({"errors": [{"code": "forbidden"}]}, status_code=403, url=forbidden_url)
        get_responses = {
            f"{INTERCOM_API_BASE}/conversations/1": _make_response(
                {"conversation_parts": {"conversation_parts": [{"id": "p1"}]}}
            ),
            forbidden_url: forbidden,
            f"{INTERCOM_API_BASE}/conversations/3": _make_response(
                {"conversation_parts": {"conversation_parts": [{"id": "p3"}]}}
            ),
        }
        session = _make_session([search_page], get_responses)

        parts = list(
            _conversation_parts_generator(session, incremental_field="updated_at", db_incremental_field_last_value=None)
        )

        assert [(p["id"], p["conversation_id"]) for p in parts] == [("p1", "1"), ("p3", "3")]

    def test_non_403_http_error_still_propagates(self) -> None:
        """500s and other transient errors must keep propagating so the
        pipeline's retry path can handle them — only 403 is per-row tolerated."""
        search_page = _make_response({"conversations": [{"id": "1"}], "pages": {"next": None}})
        get_responses = {
            f"{INTERCOM_API_BASE}/conversations/1": _make_response({}, status_code=500),
        }
        session = _make_session([search_page], get_responses)

        with pytest.raises(HTTPError) as exc_info:
            list(
                _conversation_parts_generator(
                    session, incremental_field="updated_at", db_incremental_field_last_value=None
                )
            )

        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 500

    def test_parent_search_403_still_propagates(self) -> None:
        """A 403 on `POST /conversations/search` is a real workspace-scope
        failure and must propagate — only the per-row fetch is tolerated."""
        forbidden_search = _make_response(
            {"errors": [{"code": "forbidden"}]},
            status_code=403,
            url=f"{INTERCOM_API_BASE}/conversations/search",
        )
        session = _make_session([forbidden_search], {})

        with pytest.raises(HTTPError) as exc_info:
            list(
                _conversation_parts_generator(
                    session, incremental_field="updated_at", db_incremental_field_last_value=None
                )
            )

        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 403


class TestCompanySegmentsGenerator:
    """Same shape as conversation_parts: `POST /companies/list` parent walk
    plus `GET /companies/{id}/segments` per-row. Mirrors the per-row 403 fix."""

    def test_per_row_403_is_skipped_and_other_rows_still_yield(self) -> None:
        list_page = _make_response({"data": [{"id": "c1"}, {"id": "c2"}], "pages": {"next": None}})
        get_responses = {
            f"{INTERCOM_API_BASE}/companies/c1/segments": _make_response({"data": [{"id": "s1"}]}),
            f"{INTERCOM_API_BASE}/companies/c2/segments": _make_response(
                {"errors": [{"code": "forbidden"}]},
                status_code=403,
                url=f"{INTERCOM_API_BASE}/companies/c2/segments",
            ),
        }
        session = _make_session([list_page], get_responses)

        segs = list(_company_segments_generator(session))

        assert [(s["id"], s["company_id"]) for s in segs] == [("s1", "c1")]

    def test_parent_list_403_still_propagates(self) -> None:
        forbidden_list = _make_response(
            {"errors": [{"code": "forbidden"}]},
            status_code=403,
            url=f"{INTERCOM_API_BASE}/companies/list",
        )
        session = _make_session([forbidden_list], {})

        with pytest.raises(HTTPError) as exc_info:
            list(_company_segments_generator(session))

        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 403
