import pytest

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.errors import QUERY_BUILD_BUG_CODES, QueryErrorCategory, classify_query_error


def _server_exception(code: int) -> ServerException:
    return ServerException("DB::Exception: synthetic", code=code)


class TestClassifyQueryError:
    @parameterized.expand([(code,) for code in sorted(QUERY_BUILD_BUG_CODES)])
    def test_build_bug_code_promoted_when_no_user_hogql(self, code: int) -> None:
        category = classify_query_error(_server_exception(code), has_user_authored_hogql=False)
        assert category == QueryErrorCategory.QUERY_BUILD_BUG

    @parameterized.expand([(code,) for code in sorted(QUERY_BUILD_BUG_CODES)])
    def test_build_bug_code_not_promoted_when_user_hogql(self, code: int) -> None:
        category = classify_query_error(_server_exception(code), has_user_authored_hogql=True)
        assert category != QueryErrorCategory.QUERY_BUILD_BUG

    @parameterized.expand([(code,) for code in sorted(QUERY_BUILD_BUG_CODES)])
    def test_build_bug_code_not_promoted_when_context_missing(self, code: int) -> None:
        category = classify_query_error(_server_exception(code))
        assert category != QueryErrorCategory.QUERY_BUILD_BUG

    @parameterized.expand(
        [
            (159, QueryErrorCategory.QUERY_PERFORMANCE_ERROR),
            (241, QueryErrorCategory.QUERY_PERFORMANCE_ERROR),
            (202, QueryErrorCategory.RATE_LIMITED),
            (394, QueryErrorCategory.CANCELLED),
        ]
    )
    def test_non_build_bug_codes_unchanged_with_has_user_authored_hogql_false(
        self, code: int, expected: QueryErrorCategory
    ) -> None:
        assert classify_query_error(_server_exception(code), has_user_authored_hogql=False) == expected

    def test_non_server_exception_unaffected(self) -> None:
        assert classify_query_error(ValueError("boom"), has_user_authored_hogql=False) == QueryErrorCategory.ERROR


if __name__ == "__main__":
    pytest.main([__file__])
