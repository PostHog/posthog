from typing import Any

from posthog.schema import AssistantHogQLQuery, HogQLQuery

TRUNCATED_MARKER = "...truncated"
# Must stay distinctive: query_executor detects it with a substring check over the whole formatted
# table (same way it detects TRUNCATED_MARKER), and an LLM must not mistake it for a data value.
NULL_MARKER = "(null)"


class SQLResultsFormatter:
    """
    Compresses and formats SQL results into a LLM-friendly string.
    """

    MAX_CELL_LENGTH = 500
    MAX_RESULT_CHARS = 64_000
    MIN_RESULT_CHARS = 512
    PREVIEW_GUIDANCE = (
        "Omitted rows or shortened cells are not evidence of missing data. "
        "Select fewer columns, aggregate, filter, or paginate with a stable ORDER BY to inspect more data."
    )

    def __init__(
        self,
        query: AssistantHogQLQuery | HogQLQuery,
        results: list[dict[str, Any]],
        columns: list[str],
        max_cell_length: int | None = MAX_CELL_LENGTH,
        *,
        max_result_chars: int | None = None,
    ) -> None:
        self._query = query
        self._results = results
        self._columns = columns
        self._max_cell_length = max_cell_length
        self._max_result_chars = max_result_chars
        if max_result_chars is not None and max_result_chars < self.MIN_RESULT_CHARS:
            raise ValueError("The SQL preview budget must be at least 512 characters")
        self._has_truncated_values = False

    @property
    def has_truncated_values(self) -> bool:
        return self._has_truncated_values

    def _format_cell(self, cell: Any) -> str:
        """MCP keeps JSON-only truncation; native agent previews also bound plain text."""
        if cell is None:
            # Bare str(None) yields "None", which LLMs read as a value rather than as missing data.
            return NULL_MARKER

        cell_str = str(cell)

        if cell_str == NULL_MARKER:
            # A real value that renders exactly like the marker would otherwise be indistinguishable
            # from SQL NULL, so the LLM would report present data as missing. Quote it instead.
            return f'"{NULL_MARKER}"'

        # Check if it's a dict/list or a stringified JSON (starts with { or [)
        is_json_like = isinstance(cell, dict | list) or (
            isinstance(cell, str) and cell_str and cell_str[0] in ("{", "[")
        )

        if (
            self._max_cell_length is not None
            and (is_json_like or self._max_result_chars is not None)
            and len(cell_str) > self._max_cell_length
        ):
            self._has_truncated_values = True
            prefix_length = self._max_cell_length
            if self._max_result_chars is not None:
                prefix_length = max(0, prefix_length - len(TRUNCATED_MARKER))
            return cell_str[:prefix_length] + TRUNCATED_MARKER

        return cell_str

    def _preview_notice(self, shown_rows: int, *, omitted_header: bool = False) -> str:
        details = f"Showing {shown_rows} of {len(self._results)} returned rows."
        if omitted_header:
            details += " The header or first row is too wide to show."
        if self._has_truncated_values:
            details += " Some cells were shortened."
        return f"[SQL result preview: {details} {self.PREVIEW_GUIDANCE}]"

    @classmethod
    def bound_fallback(cls, content: str, max_result_chars: int | None) -> str:
        if max_result_chars is None or len(content) <= max_result_chars:
            return content
        notice = f"\n[Incomplete SQL result preview. Any JSON shown may be cut off. {cls.PREVIEW_GUIDANCE}]"
        return content[: max(0, max_result_chars - len(notice))] + notice

    def format(self) -> str:
        self._has_truncated_values = False
        lines: list[str] = []
        header = "|".join(self._columns)
        budget = self._max_result_chars
        if budget is not None and len(header) > budget:
            return self._preview_notice(0, omitted_header=True)
        lines.append(header)
        chars = len(header)
        shown_rows = 0
        for row in self._results:
            if isinstance(row, dict):
                line = "|".join([self._format_cell(cell) for cell in row.values()])
            else:
                line = "|".join([self._format_cell(cell) for cell in row])  # type: ignore
            if budget is not None and chars + len(line) + 1 > budget:
                break
            lines.append(line)
            chars += len(line) + 1
            shown_rows += 1

        if budget is not None and (shown_rows < len(self._results) or self._has_truncated_values):
            notice = self._preview_notice(shown_rows, omitted_header=shown_rows == 0 and bool(self._results))
            while shown_rows > 0 and chars + len(notice) + 1 > budget:
                chars -= len(lines.pop()) + 1
                shown_rows -= 1
                notice = self._preview_notice(shown_rows, omitted_header=shown_rows == 0)
            if chars + len(notice) + 1 > budget:
                return self._preview_notice(0, omitted_header=True)
            lines.append(notice)

        return "\n".join(lines)
