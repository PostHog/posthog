from .utils import format_duration, format_matrix, format_number


class PathsResultsFormatter:
    """
    Compresses and formats paths results into a LLM-friendly string.

    Example answer:
    ```
    Source|Target|Users|Avg. conversion time
    1_/home|2_/pricing|150|2m 30s
    1_/home|2_/docs|80|1m 15s
    2_/pricing|3_/signup|120|45s
    ```
    """

    def __init__(self, results: list[dict]):
        self._results = results

    def format(self) -> str:
        results = self._results

        if not results:
            return "No data recorded for this time period."

        matrix: list[list[str]] = [["Source", "Target", "Users", "Avg. conversion time"]]
        for link in results:
            row = [
                str(link["source"]),
                str(link["target"]),
                format_number(link["value"]),
                format_duration(link["average_conversion_time"]) or "0s",
            ]
            matrix.append(row)

        return format_matrix(matrix)
