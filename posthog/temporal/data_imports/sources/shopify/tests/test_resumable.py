from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.shopify.constants import ABANDONED_CHECKOUTS, ORDERS, SHOPIFY_GRAPHQL_OBJECTS
from posthog.temporal.data_imports.sources.shopify.shopify import (
    PHASE_ALL,
    PHASE_EARLIEST,
    PHASE_LATEST,
    ShopifyResumeConfig,
    _make_paginated_shopify_request,
    shopify_source,
)


def _build_response(
    object_name: str, nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None
) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {
            object_name: {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            }
        }
    }
    return response


def _make_manager(can_resume: bool = False, resume_state: ShopifyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


def _record_post_vars(sess: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """Capture the `variables` dict by value at call time.

    The production code passes the `variables` dict by reference and mutates it
    between pages, so reading it off `call_args_list` after the fact reflects
    only the final state, not per-call state.
    """
    captured: list[dict[str, Any]] = []
    iter_responses = iter(responses)

    def _post(url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> MagicMock:
        captured.append(dict((json or {}).get("variables", {})))
        return next(iter_responses)

    sess.post.side_effect = _post
    return captured


class TestMakePaginatedShopifyRequest:
    def test_saves_state_after_each_page_except_final(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="cursor-1"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=True, end_cursor="cursor-2"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "3"}], has_next_page=False, end_cursor=None),
        ]

        batches = list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
                resumable_source_manager=manager,
            )
        )

        assert len(batches) == 3
        # save_state fires only when has_next_page is True (final page is terminal).
        assert manager.save_state.call_count == 2
        saved_configs = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved_configs[0] == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-1")
        assert saved_configs[1] == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-2")

    def test_seeds_initial_cursor_on_resume(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        captured = _record_post_vars(
            sess, [_build_response(ABANDONED_CHECKOUTS, [{"id": "5"}], has_next_page=False, end_cursor=None)]
        )

        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
                initial_cursor="resume-cursor",
                resumable_source_manager=manager,
            )
        )

        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "resume-cursor"

    def test_tags_saved_state_with_phase(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        manager = _make_manager()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="next"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=False, end_cursor=None),
        ]

        list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                query="created_at:>'2026-01-01'",
                phase=PHASE_LATEST,
                resumable_source_manager=manager,
            )
        )

        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args_list[0].args[0]
        assert saved == ShopifyResumeConfig(phase=PHASE_LATEST, cursor="next")

    def test_no_save_without_manager(self) -> None:
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS[ABANDONED_CHECKOUTS]
        logger = MagicMock()
        sess = MagicMock()
        sess.post.side_effect = [
            _build_response(ABANDONED_CHECKOUTS, [{"id": "1"}], has_next_page=True, end_cursor="next"),
            _build_response(ABANDONED_CHECKOUTS, [{"id": "2"}], has_next_page=False, end_cursor=None),
        ]

        batches = list(
            _make_paginated_shopify_request(
                "https://example.invalid/graphql",
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
            )
        )

        assert len(batches) == 2


@pytest.fixture(autouse=True)
def _mock_access_token():
    with patch(
        "posthog.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token",
        return_value="test-token",
    ):
        yield


class TestShopifySourceResume:
    def test_fresh_full_refresh_starts_without_cursor_and_saves_state(self) -> None:
        logger = MagicMock()
        manager = _make_manager(can_resume=False)

        with patch("posthog.temporal.data_imports.sources.shopify.shopify.requests.Session") as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [
                    _build_response(ORDERS, [{"id": "1"}], has_next_page=True, end_cursor="cursor-1"),
                    _build_response(ORDERS, [{"id": "2"}], has_next_page=False, end_cursor=None),
                ],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            batches = list(source.items())

        assert len(batches) == 2
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args_list[0].args[0]
        assert saved == ShopifyResumeConfig(phase=PHASE_ALL, cursor="cursor-1")

        assert "cursor" not in captured[0]

    def test_resume_full_refresh_seeds_cursor_and_skips_initial_request(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_ALL, cursor="resume-here")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch("posthog.temporal.data_imports.sources.shopify.shopify.requests.Session") as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [_build_response(ORDERS, [{"id": "3"}], has_next_page=False, end_cursor=None)],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            batches = list(source.items())

        assert len(batches) == 1
        manager.load_state.assert_called_once()
        # Exactly one request: the resumed page. The initial (cursor-less) request is skipped.
        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "resume-here"

    def test_resume_latest_phase_skips_earliest_sweep(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_LATEST, cursor="latest-cursor")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch("posthog.temporal.data_imports.sources.shopify.shopify.requests.Session") as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [_build_response(ORDERS, [{"id": "9"}], has_next_page=False, end_cursor=None)],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value="2026-01-10",
                db_incremental_field_earliest_value="2026-01-01",
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
            )
            batches = list(source.items())

        assert len(batches) == 1
        # Only the latest sweep runs, seeded with the resume cursor.
        assert sess.post.call_count == 1
        assert captured[0]["cursor"] == "latest-cursor"
        assert captured[0]["query"] == "updated_at:>'2026-01-10'"

    def test_resume_earliest_phase_runs_remaining_earliest_then_latest(self) -> None:
        logger = MagicMock()
        resume_state = ShopifyResumeConfig(phase=PHASE_EARLIEST, cursor="earliest-cursor")
        manager = _make_manager(can_resume=True, resume_state=resume_state)

        with patch("posthog.temporal.data_imports.sources.shopify.shopify.requests.Session") as session_cls:
            sess = session_cls.return_value
            captured = _record_post_vars(
                sess,
                [
                    # remaining earliest page (final)
                    _build_response(ORDERS, [{"id": "e1"}], has_next_page=False, end_cursor=None),
                    # latest sweep starts fresh (no cursor)
                    _build_response(ORDERS, [{"id": "l1"}], has_next_page=False, end_cursor=None),
                ],
            )

            source = shopify_source(
                shopify_store_id="store",
                shopify_client_id="id",
                shopify_client_secret="secret",
                graphql_object_name=ORDERS,
                db_incremental_field_last_value="2026-01-10",
                db_incremental_field_earliest_value="2026-01-01",
                logger=logger,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
            )
            batches = list(source.items())

        assert len(batches) == 2
        assert sess.post.call_count == 2

        assert captured[0]["cursor"] == "earliest-cursor"
        assert captured[0]["query"] == "updated_at:<'2026-01-01'"

        assert "cursor" not in captured[1]
        assert captured[1]["query"] == "updated_at:>'2026-01-10'"
