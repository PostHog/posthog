import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.data_catalog.backend.logic import agent_sessions
from products.data_catalog.backend.logic.agent_sessions import (
    ChainsTruncated,
    Piece,
    PieceCall,
    StitchUnavailable,
    conversation_of,
    fetch_candidate_chains,
    joined_sessions,
    link_chain,
    merge_shared_conversations,
    stitch_sessions_into_snapshot,
)

AT = datetime(2026, 11, 2, 9, tzinfo=UTC)


def _piece(
    piece_id: str,
    minutes: float,
    *,
    client: str = "claude-code",
    note: str = "weekly signups",
    conversation: str = "",
    person: str = "d1",
) -> Piece:
    at = AT + timedelta(minutes=minutes)
    return Piece(
        piece_id=piece_id,
        person=person,
        source="mcp",
        client=client,
        calls=(PieceCall(at=at, tool="execute-sql", note=note),),
        conversation_id=conversation,
    )


class _Reply:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_Reply":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class _Client:
    def __init__(self, *texts: str) -> None:
        replies = iter(texts)
        self.prompts: list[str] = []

        def stream(**kwargs: Any) -> _Reply:
            self.prompts.append(kwargs["messages"][0]["content"])
            # The last reply repeats, so a retry of a bad reply gets the same bad reply.
            return _Reply(next(replies, texts[-1]))

        self.messages = SimpleNamespace(stream=stream)


@asynccontextmanager
async def _opened(client: _Client) -> AsyncIterator[_Client]:
    yield client


class TestSessionStitching(SimpleTestCase):
    @parameterized.expand(
        [
            ("joined", '{"labels": ["C1", "C1"]}', 1, [("a", "b")], 0),
            ("apart", '{"labels": ["C1", "C2"]}', 1, [("a",), ("b",)], 0),
            ("past_the_gap", '{"labels": ["C1", "C1"]}', 45, [("a",), ("b",)], 0),
            ("wrong_count", '{"labels": ["C1"]}', 1, [("a",), ("b",)], 1),
            ("no_json", "I think they belong together.", 1, [("a",), ("b",)], 1),
            (
                "corrected",
                '{"labels": ["C1"]} Wait, there are two pieces. {"labels": ["C1", "C1"]}',
                1,
                [("a", "b")],
                0,
            ),
            ("empty_labels", '{"labels": ["", " "]}', 1, [("a",), ("b",)], 1),
            ("fixed_on_retry", ('{"labels": ["C1", "C1"],"}', '{"labels": ["C1", "C1"]}'), 1, [("a", "b")], 0),
        ]
    )
    def test_only_a_valid_reply_within_the_gap_joins_pieces(
        self, _name: str, reply: str | tuple[str, ...], minutes: int, expected: list[tuple[str, ...]], failed: int
    ) -> None:
        replies = (reply,) if isinstance(reply, str) else reply
        links = async_to_sync(link_chain)(_Client(*replies), [_piece("a", 0), _piece("b", minutes)])  # type: ignore[arg-type]

        assert sorted(links.conversations) == expected
        assert links.failed_calls == failed

    def test_pieces_with_one_conversation_id_join_past_the_gap_without_a_model_call(self) -> None:
        chains = merge_shared_conversations(
            [
                [_piece("a", 0, conversation="thread")],
                [_piece("c", 50)],
                [_piece("b", 45, conversation="thread")],
                [_piece("d", 46, conversation="thread", person="d2")],
            ]
        )
        client = _Client('{"labels": ["C1", "C2"]}')

        links = async_to_sync(link_chain)(client, chains[0])  # type: ignore[arg-type]

        assert [[piece.piece_id for piece in chain] for chain in chains] == [["a", "b"], ["c"], ["d"]]
        assert links.conversations == (("a", "b"),)
        assert links.model_calls == 0

    def test_the_gap_counts_from_the_real_end_of_a_piece_whose_calls_were_cut(self) -> None:
        long_piece = Piece(
            piece_id="a",
            person="d1",
            source="mcp",
            client="claude-code",
            calls=(PieceCall(at=AT, tool="execute-sql", note="weekly signups"),),
            last_call_at=AT + timedelta(minutes=40),
        )

        links = async_to_sync(link_chain)(_Client('{"labels": ["C1", "C1"]}'), [long_piece, _piece("b", 50)])  # type: ignore[arg-type]

        assert links.conversations == (("a", "b"),)

    def test_a_long_piece_shows_both_ends_and_each_model_call_sends_a_heartbeat(self) -> None:
        busy = Piece(
            piece_id="a",
            person="d1",
            source="mcp",
            client="claude-code",
            calls=tuple(
                PieceCall(at=AT + timedelta(seconds=step), tool="execute-sql", note=f"step {step}")
                for step in range(20)
            ),
        )
        client = _Client('{"labels": ["C1", "C1"]}')
        beats: list[None] = []

        links = async_to_sync(link_chain)(client, [busy, _piece("b", 1)], lambda: beats.append(None))  # type: ignore[arg-type]

        assert "14 more calls" in client.prompts[0] and "step 10" not in client.prompts[0]
        assert len(beats) == links.model_calls == 1

    @parameterized.expand(
        [
            ("continues_an_open_conversation", "open-1", [("p0",), tuple(f"p{n}" for n in range(1, 31))]),
            ("reuses_the_label_of_a_closed_one", "C1", [("p0",), tuple(f"p{n}" for n in range(1, 30)), ("p30",)]),
        ]
    )
    def test_a_later_block_continues_only_a_conversation_that_is_still_open(
        self, _name: str, label: str, expected: list[tuple[str, ...]]
    ) -> None:
        # The first block closes p0 long before the second block starts, and keeps p1 to p29 open.
        chain = [_piece("p0", 0), *(_piece(f"p{n}", 40 + n) for n in range(1, 31))]
        client = _Client(json.dumps({"labels": ["C1"] + ["C2"] * 29}), json.dumps({"labels": [label]}))

        links = async_to_sync(link_chain)(client, chain)  # type: ignore[arg-type]

        assert sorted(links.conversations) == sorted(expected)
        assert "- open-1," in client.prompts[1] and "open-2" not in client.prompts[1]

    @parameterized.expand(
        [
            ("every_call_fails", ("I think they belong together.",), 1, "weekly signups", None),
            ("a_join_without_notes_is_stored", ('{"labels": ["C1", "C1"]}',), 1, "", [["0a", "0b"]]),
            ("half_the_calls_fail", ('{"labels": ["C1", "C1"]}', "I think they belong together."), 2, "signups", None),
        ]
    )
    def test_the_step_stores_every_join_and_fails_when_too_many_calls_fail(
        self, _name: str, replies: tuple[str, ...], chain_count: int, note: str, stored: list[list[str]] | None
    ) -> None:
        chains = [
            [_piece(f"{index}a", 0, note=note), _piece(f"{index}b", 1, note=note)] for index in range(chain_count)
        ]
        written: list[dict[str, Any]] = []

        def write(_team_id: int, _snapshot_id: object, **sections: Any) -> None:
            written.append(sections)

        with (
            patch.object(agent_sessions, "_load_chains", lambda **_: chains),
            patch.object(agent_sessions, "build_async_anthropic_client", lambda **_: _opened(_Client(*replies))),
            patch.object(agent_sessions, "write_payload_sections", write),
            pytest.raises(StitchUnavailable) if stored is None else nullcontext(),
        ):
            async_to_sync(stitch_sessions_into_snapshot)(
                team_id=1, snapshot_id=uuid4(), telemetry_team_id=1, heartbeat=lambda: None
            )

        assert written == ([] if stored is None else [{"conversations": stored}])

    def test_a_stored_join_makes_one_conversation_and_other_pieces_stand_alone(self) -> None:
        chain = [_piece("a", 0), _piece("b", 2, note="the same signups question"), _piece("c", 4, note="pricing")]

        joined = joined_sessions([chain], [["a", "b"]])

        assert joined.members == {"a": ("a", "b"), "c": ("c",)}
        assert [session.notes for session in joined.sessions] == [
            ("weekly signups", "the same signups question"),
            ("pricing",),
        ]
        assert conversation_of([["a", "b"]]) == {"a": "a", "b": "a"}


class TestCandidateChainsQuery(ClickhouseTestMixin, BaseTest):
    def _call(self, session: str, at: datetime, tool: str = "execute-sql", **properties: object) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=at,
            properties={
                "$session_id": session,
                "$mcp_tool_name": tool,
                "$mcp_intent": f"note for {session}",
                "$mcp_client_name": "claude-code",
                "$mcp_project_uuid": str(self.team.uuid),
                **properties,
            },
        )

    @parameterized.expand(
        [
            ("no_lookback", timedelta(0), [["inside"]]),
            ("a_day_of_lookback", timedelta(days=1), [["before", "inside"]]),
        ]
    )
    def test_a_lookback_adds_earlier_pieces_only_to_chains_that_reach_the_window(
        self, _name: str, lookback: timedelta, expected: list[list[str]]
    ) -> None:
        self._call("before", AT - timedelta(minutes=20))
        self._call("inside", AT)
        self._call("only-before", AT - timedelta(hours=5))
        flush_persons_and_events()

        chains = fetch_candidate_chains(
            team=self.team,
            telemetry_team=self.team,
            window_start=AT,
            window_end=AT + timedelta(days=1),
            chain_limit=100,
            lookback=lookback,
        )

        assert [[piece.piece_id for piece in chain] for chain in chains] == expected

    @parameterized.expand([("under_the_bound", 3, False), ("at_the_bound", 2, True)])
    def test_a_chain_query_that_reaches_its_row_bound_fails(self, _name: str, row_limit: int, fails: bool) -> None:
        self._call("one", AT)
        self._call("two", AT + timedelta(hours=2))
        flush_persons_and_events()

        with (
            patch.object(agent_sessions, "MAX_SELECT_RETURNED_ROWS", row_limit),
            pytest.raises(ChainsTruncated) if fails else nullcontext(),
        ):
            fetch_candidate_chains(
                team=self.team,
                telemetry_team=self.team,
                window_start=AT - timedelta(hours=1),
                window_end=AT + timedelta(days=1),
                chain_limit=100,
            )

    def test_the_sample_keeps_every_chain_of_a_conversation(self) -> None:
        self._call("described", AT, tool="metric-describe", **{"$mcp_conversation_id": "t2"})
        self._call("answered", AT + timedelta(hours=2), **{"$mcp_conversation_id": "t2"})
        flush_persons_and_events()

        chains = fetch_candidate_chains(
            team=self.team,
            telemetry_team=self.team,
            window_start=AT - timedelta(hours=1),
            window_end=AT + timedelta(days=1),
            chain_limit=1,
        )

        assert [[piece.piece_id for piece in chain] for chain in chains] == [["described", "answered"]]

    def test_pieces_chain_within_the_gap_and_a_chain_needs_a_data_tool(self) -> None:
        self._call("first", AT, **{"$mcp_conversation_id": "thread"})
        self._call("second", AT + timedelta(minutes=10), tool="metric-list")
        self._call("later", AT + timedelta(hours=2))
        self._call("resumed", AT + timedelta(hours=4), **{"$mcp_conversation_id": "thread"})
        self._call("docs-only", AT + timedelta(hours=5), tool="docs-search")
        self._call("described", AT + timedelta(hours=6), tool="metric-describe", **{"$mcp_conversation_id": "t2"})
        self._call("answered", AT + timedelta(hours=8), **{"$mcp_conversation_id": "t2"})
        self._call("only-read", AT + timedelta(hours=10), tool="metric-describe", **{"$mcp_conversation_id": "t3"})
        self._call("other-project", AT + timedelta(minutes=5), **{"$mcp_project_uuid": "another-project"})
        self._call("other-client", AT + timedelta(minutes=5), **{"$mcp_client_name": "codex"})
        flush_persons_and_events()

        chains = fetch_candidate_chains(
            team=self.team,
            telemetry_team=self.team,
            window_start=AT - timedelta(hours=1),
            window_end=AT + timedelta(days=1),
            chain_limit=100,
        )

        assert sorted([piece.piece_id for piece in chain] for chain in chains) == [
            ["described", "answered"],
            ["first", "second", "resumed"],
            ["later"],
            ["other-client"],
        ]
