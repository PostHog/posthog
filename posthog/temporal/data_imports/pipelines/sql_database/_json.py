import json
from sqlalchemy import String, TypeDecorator


class BigQueryJSON(TypeDecorator):
    """
    SQLAlchemy 2.0 compatible JSON type for BigQuery

    This implementation uses STRING as the underlying type since
    that's how BigQuery stores JSON.
    """

    impl = String
    cache_ok = True

    def __init__(self, none_as_null: bool = False) -> None:
        super().__init__()
        self.none_as_null = none_as_null

        # Add these for BigQuery dialect compatibility
        self._json_serializer = json.dumps
        self._json_deserializer = json.loads

    def process_bind_param(self, value, dialect):
        if value is None:
            return None if self.none_as_null else "null"
        return self._json_deserializer(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self._json_serializer(value)
