from parameterized import parameterized

from posthog.session_recordings.queries.combine_session_ids_for_filtering import combine_session_id_filters


class TestCombineSessionIds:
    @parameterized.expand(
        [
            ("Both None - no filtering", None, None, None),
            ("both empty", [], [], []),
            ("right empty list means match 0 session", None, [], []),
            ("left empty list means match 0 sessions", [], None, []),
            ("Only comment_session_ids provided", None, ["a", "a", "b", "c"], ["a", "b", "c"]),
            ("Only existing_ids provided ", ["x", "x", "y", "z"], None, ["x", "y", "z"]),
            ("Both provided - intersection", ["a", "b", "b", "c"], ["b", "c", "c", "d"], ["b", "c"]),
            ("no overlap", ["a", "b"], ["c", "d"], []),
            ("complete overlap", ["a", "b", "c"], ["a", "b", "c"], ["a", "b", "c"]),
            ("empty comment_session_ids", [], ["a", "b"], []),
            ("empty existing_ids", ["a", "b"], [], []),
        ],
    )
    def test_combine_session_id_filters(
        self,
        _name: str,
        comment_session_ids: list[str] | None,
        existing_ids: list[str] | None,
        expected: list[str] | None,
    ) -> None:
        result = combine_session_id_filters(comment_session_ids, existing_ids)
        if expected is None:
            assert result is None
        else:
            # include an assertion it is not None to help mypy
            assert result is not None and sorted(result) == sorted(expected)
