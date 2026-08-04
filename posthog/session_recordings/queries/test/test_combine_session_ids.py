from parameterized import parameterized

from posthog.schema import (
    EventPropertyFilter,
    FilterLogicalOperator,
    PersonPropertyFilter,
    PropertyOperator,
    RecordingsQuery,
)

from posthog.session_recordings.queries.combine_session_ids_for_filtering import (
    combine_session_id_filters,
    extract_session_id_property_filter,
)


class TestExtractSessionIdPropertyFilter:
    @parameterized.expand(
        [
            (
                "exact $session_id filter is moved into session_ids",
                [EventPropertyFilter(key="$session_id", operator=PropertyOperator.EXACT, value="abc")],
                None,
                None,
                ["abc"],
            ),
            (
                "in $session_id filter with multiple values is moved into session_ids",
                [EventPropertyFilter(key="$session_id", operator=PropertyOperator.IN_, value=["abc", "def"])],
                None,
                None,
                ["abc", "def"],
            ),
            (
                "other property filters are preserved alongside an extracted $session_id filter",
                [
                    EventPropertyFilter(key="$session_id", operator=PropertyOperator.EXACT, value="abc"),
                    PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com"),
                ],
                None,
                [PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com")],
                ["abc"],
            ),
            (
                "extracted session ids are intersected with any session_ids already on the query",
                [EventPropertyFilter(key="$session_id", operator=PropertyOperator.EXACT, value="abc")],
                ["abc", "def"],
                None,
                ["abc"],
            ),
            (
                "no $session_id filter present leaves the query untouched",
                [PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com")],
                None,
                [PersonPropertyFilter(key="email", operator=PropertyOperator.EXACT, value="a@b.com")],
                None,
            ),
            (
                "no properties at all leaves the query untouched",
                None,
                None,
                None,
                None,
            ),
        ],
    )
    def test_extracts_exact_session_id_filters_under_and(
        self,
        _name: str,
        properties: list | None,
        existing_session_ids: list[str] | None,
        expected_properties: list | None,
        expected_session_ids: list[str] | None,
    ) -> None:
        query = RecordingsQuery(
            operand=FilterLogicalOperator.AND_, properties=properties, session_ids=existing_session_ids
        )

        result = extract_session_id_property_filter(query)

        assert result.properties == expected_properties
        if expected_session_ids is None:
            assert result.session_ids is None
        else:
            assert result.session_ids is not None and sorted(result.session_ids) == sorted(expected_session_ids)

    def test_does_not_extract_from_an_or_query(self) -> None:
        query = RecordingsQuery(
            operand=FilterLogicalOperator.OR_,
            properties=[EventPropertyFilter(key="$session_id", operator=PropertyOperator.EXACT, value="abc")],
        )

        result = extract_session_id_property_filter(query)

        assert result.properties == query.properties
        assert result.session_ids is None


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
