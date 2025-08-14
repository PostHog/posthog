from parameterized import parameterized

from posthog.session_recordings.queries.combine_session_ids_for_filtering import combine_session_id_filters


class TestCombineSessionIds:
    @parameterized.expand(
        [
            ("Both None - no filtering", None, None, None),
            ("Only comment_session_ids provided", None, ["a", "b", "c"], ["a", "b", "c"]),
            ("comment session ids deduplication", None, ["a", "a", "b"], ["a", "b"]),
            ("left empty list means match 0 sessions", [], None, []),
            ("right empty list means match 0 session", None, [], []),
            ("Only existing_ids provided ", ["x", "y", "z"], None, ["x", "y", "z"]),
            ("existing id deduplication", ["x", "x", "y"], None, ["x", "y"]),
            ("Both provided - intersection", ["a", "b", "c"], ["b", "c", "d"], ["b", "c"]),
            ("no overlap", ["a", "b"], ["c", "d"], []),
            ("complete overlap", ["a", "b", "c"], ["a", "b", "c"], ["a", "b", "c"]),
            ("empty comment_session_ids", [], ["a", "b"], []),
            ("empty existing_ids", ["a", "b"], [], []),
            ("both empty", [], [], []),
            ("Duplicates in intersection", ["a", "a", "b", "b"], ["b", "b", "c"], ["b"]),
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
            assert sorted(result) == sorted(expected)
