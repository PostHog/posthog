from typing import Any

from posthog.schema import AssistantHogQLQuery, HogQLQuery

TRUNCATED_MARKER = "...truncated"


class SQLResultsFormatter:
    """
    Compresses and formats SQL results into a LLM-friendly string.
    """

    MAX_CELL_LENGTH = 500

    def __init__(
        self,
        query: AssistantHogQLQuery | HogQLQuery,
        results: list[dict[str, Any]],
        columns: list[str],
        max_cell_length: int | None = MAX_CELL_LENGTH,
    ):
        self._query = query
        self._results = results
        self._columns = columns
        self._max_cell_length = max_cell_length
        self._has_truncated_values = False

    @property
    def has_truncated_values(self) -> bool:
        return self._has_truncated_values

    def _format_cell(self, cell: Any) -> str:
        """Format a single cell value, truncating large dicts/arrays or stringified JSON."""
        cell_str = str(cell)

        # Check if it's a dict/list or a stringified JSON (starts with { or [)
        is_json_like = isinstance(cell, dict | list) or (
            isinstance(cell, str) and cell_str and cell_str[0] in ("{", "[")
        )

        if self._max_cell_length is not None and is_json_like and len(cell_str) > self._max_cell_length:
            self._has_truncated_values = True
            return cell_str[: self._max_cell_length] + TRUNCATED_MARKER

        return cell_str

    def format(self) -> str:
        lines: list[str] = []
        lines.append("|".join(self._columns))
        for row in self._results:
            if isinstance(row, dict):
                lines.append("|".join([self._format_cell(cell) for cell in row.values()]))
            else:
                lines.append("|".join([self._format_cell(cell) for cell in row]))  # type: ignore

        return "\n".join(lines)
