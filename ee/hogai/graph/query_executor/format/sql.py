from typing import Any

from posthog.schema import AssistantHogQLQuery, HogQLQuery


class SQLResultsFormatter:
    """
    Compresses and formats SQL results into a LLM-friendly string.
    """

    def __init__(self, query: AssistantHogQLQuery | HogQLQuery, results: list[dict[str, Any]], columns: list[str]):
        self._query = query
        self._results = results
        self._columns = columns

    def format(self) -> str:
        lines: list[str] = []
        lines.append("|".join(self._columns))
        for row in self._results:
            if isinstance(row, dict):
                lines.append("|".join([str(cell) for cell in row.values()]))
            else:
                lines.append("|".join([str(cell) for cell in row]))  # type: ignore
        return "\n".join(lines)
