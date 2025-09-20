import pytest

# ensure asserts in the utils module are rewritten by pytest
# see: https://docs.pytest.org/en/stable/how-to/writing_plugins.html#assertion-rewriting
pytest.register_assert_rewrite("products.batch_exports.backend.tests.temporal.destinations.snowflake.utils")
