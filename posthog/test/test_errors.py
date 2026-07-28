from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException

from posthog.errors import ExposedCHQueryError, wrap_clickhouse_query_error


class TestWrapClickhouseQueryError(SimpleTestCase):
    def test_incorrect_element_of_set_is_user_safe(self):
        # A mismatched-arity IN clause tuple is a mistake in the user's own SQL, so it should
        # surface as a user-facing error rather than an internal exception.
        error = wrap_clickhouse_query_error(ServerException("Incorrect size of tuple in set: 4 instead of 2", code=124))
        assert isinstance(error, ExposedCHQueryError)
        assert str(error) == "Mismatched number of columns in an IN clause tuple."
