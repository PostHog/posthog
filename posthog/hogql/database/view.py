from typing import Dict, Any

from posthog.hogql.database.models import LazyTable


# TOOD: Is this the right way to do the subquery?
class View(LazyTable):
    query: str
    name: str

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return

    def to_printed_hogql(self):
        return

    def to_printed_clickhouse(self, context):
        return
