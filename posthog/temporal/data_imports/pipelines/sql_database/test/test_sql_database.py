from unittest.mock import MagicMock

from posthog.temporal.data_imports.pipelines.sql_database import get_column_hints


def _setup(return_value):
    mock_engine = MagicMock()
    mock_engine_enter = MagicMock()
    mock_connection = MagicMock()
    mock_result = MagicMock()

    mock_engine.configure_mock(**{"connect.return_value": mock_engine_enter})
    mock_engine_enter.configure_mock(**{"__enter__.return_value": mock_connection})
    mock_connection.configure_mock(**{"execute.return_value": mock_result})
    mock_result.configure_mock(**{"fetchall.return_value": return_value})

    return mock_engine


def test_get_column_hints_numeric_no_results():
    mock_engine = _setup([])

    assert get_column_hints(mock_engine, "some_schema", "some_table") == {}


def test_get_column_hints_numeric_with_scale_and_precision():
    mock_engine = _setup([("column", "numeric", 10, 2)])

    assert get_column_hints(mock_engine, "some_schema", "some_table") == {
        "column": {"data_type": "decimal", "precision": 10, "scale": 2}
    }


def test_get_column_hints_numeric_with_missing_scale_and_precision():
    mock_engine = _setup([("column", "numeric", None, None)])

    assert get_column_hints(mock_engine, "some_schema", "some_table") == {
        "column": {"data_type": "decimal", "precision": 76, "scale": 32}
    }


def test_get_column_hints_numeric_with_no_numeric():
    mock_engine = _setup([("column", "bigint", None, None)])

    assert get_column_hints(mock_engine, "some_schema", "some_table") == {}
