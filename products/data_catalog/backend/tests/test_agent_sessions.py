from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.data_catalog.backend.logic.agent_sessions import (
    Piece,
    PieceCall,
    candidate_chains,
    conversation_of,
    fetch_candidate_chains,
    joined_sessions,
    link_chain,
)

AT = datetime(2026, 11, 2, 9, tzinfo=UTC)


def _piece(piece_id: str, minutes: float, *, client: str = "claude-code", note: str = "weekly signups") -> Piece:
    at = AT + timedelta(minutes=minutes)
    return Piece(
        piece_id=piece_id,
        person="d1",
        source="mcp",
        client=client,
        calls=(PieceCall(at=at, tool="execute-sql", note=note),),
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


class TestSessionStitching(SimpleTestCase):
    def test_a_chain_breaks_on_a_long_gap_and_never_crosses_clients(self) -> None:
        chains = candidate_chains([_piece("a", 0), _piece("b", 29), _piece("c", 60), _piece("d", 1, client="codex")])

        assert sorted([piece.piece_id for piece in chain] for chain in chains) == [["a", "b"], ["c"], ["d"]]

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

    def test_pieces_chain_within_the_gap_and_a_chain_needs_a_data_tool(self) -> None:
        self._call("first", AT)
        self._call("second", AT + timedelta(minutes=10), tool="metric-list")
        self._call("later", AT + timedelta(hours=2))
        self._call("docs-only", AT + timedelta(hours=5), tool="docs-search")
        self._call("other-project", AT + timedelta(minutes=5), **{"$mcp_project_uuid": "another-project"})
        flush_persons_and_events()

        chains = fetch_candidate_chains(
            team=self.team,
            telemetry_team=self.team,
            window_start=AT - timedelta(hours=1),
            window_end=AT + timedelta(days=1),
            chain_limit=100,
        )

        assert sorted([piece.piece_id for piece in chain] for chain in chains) == [["first", "second"], ["later"]]
