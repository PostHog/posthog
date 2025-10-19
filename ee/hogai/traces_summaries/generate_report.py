import json
from pathlib import Path
from typing import Any
import structlog

from explain_clusters import ClusterizedSuggestion, ExplainedClusterizedSuggestionsGroup


def _calculate_confidence(avg_distance: float) -> str:
    if avg_distance > 0.9:
        return "Great"
    elif avg_distance > 0.75:
        return "Good"
    else:
        return "Medium"


def _list_trace_ids(suggestions: list[ClusterizedSuggestion]) -> str:
    max_trace_ids = 3
    if len(suggestions) <= max_trace_ids:
        return ",".join([f'`{suggestion["trace_id"]}`' for suggestion in suggestions])
    else:
        return (
            ",".join([f'`{suggestion["trace_id"]}`' for suggestion in suggestions[:max_trace_ids]])
            + f", and {len(suggestions) - max_trace_ids} more..."
        )


def _pick_summary_for_example(suggestions: list[ClusterizedSuggestion], cluster_label: str) -> str | None:
    for suggestion in suggestions:
        # Avoid non-English summaries and malformed summaries
        if (
            "á" not in suggestion["summary"]
            and " saat " not in suggestion["summary"]
            and "YAML Syntax Error:" not in suggestion["summary"]
        ):
            return suggestion["summary"].replace("  ", " ").replace(" .", ".")  # Just in case
    else:
        logger.warning(f"No non-English summary found for cluster {cluster_label}")
        return None


def _organize_issues_section(
    named_clusters: dict[str, ExplainedClusterizedSuggestionsGroup], header: str, description: str, limit: int
) -> str:
    issue_section_report = f"## {header}\n"
    issue_section_report += "\n\n"
    issue_section_report += f"{description} `Showing {limit} of {max(len(named_clusters.values()), limit)} cases`\n"
    malformed_traces = ["ClickHouse SQL Syntax Errors And Limitations", "ClickHouse SQL Syntax Errors Troubleshooting"]
    issues_mentioned = 0
    for cluster_label, cluster in named_clusters.items():
        # Don't keep topics with confidence below "Good"
        if _calculate_confidence(cluster.avg_distance) not in ["Good", "Great"]:
            continue
        # Keep only English examples
        example_summary = _pick_summary_for_example(suggestions=cluster.suggestions, cluster_label=cluster_label)
        if example_summary is None:
            continue
        # Ignore malformed traces
        print(cluster.name)
        if cluster.name.strip() in malformed_traces:
            continue
        issues_mentioned += 1
        if issues_mentioned > limit:
            # Show limited amount of issues in the section
            break
        issue_section_report += f"### {cluster.name}\n"
        issue_section_report += f"- Confidence: {_calculate_confidence(cluster.avg_distance)}\n"
        issue_section_report += f"- Linked traces: {len(cluster.suggestions)} ({_list_trace_ids(cluster.suggestions)})"
        issue_section_report += "\n\n"
        issue_section_report += "*Example trace summary:*\n"
        # issue_section_report += f"```\n"
        issue_section_report += f"> {example_summary.replace("\n", "\n >")}\n"
        # issue_section_report += f"```\n"
    return issue_section_report


logger = structlog.get_logger(__name__)
if __name__ == "__main__":
    # Load named segments
    input_groups_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/groups")
    input_named_clusters_path = input_groups_dir_path / "explained_clusters_25.json"
    with open(input_named_clusters_path) as f:
        input_named_clusters_raw: dict[str, Any] = json.load(f)
        input_named_clusters: dict[str, ExplainedClusterizedSuggestionsGroup] = {
            key: ExplainedClusterizedSuggestionsGroup(**value) for key, value in input_named_clusters_raw.items()
        }
    # Calculate total number of traces
    analyzed_traces_count = 16000  # Can calculate from CSV rows, but feel lazy
    # Calculate number of summarized traces
    stringified_traces_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
    summarized_traces_count = len(list(stringified_traces_dir_path.iterdir()))
    # Generate markdown report
    report = "# Traces Summarization Report (14.09.2025 - 17.09.2025)"
    report += "\n\n"
    report += f"- Analyzed traces: {analyzed_traces_count}\n"
    report += f"- Summarized traces: {summarized_traces_count}\n"
    report += f"- Issues found: {len(input_named_clusters)}"
    report += "\n\n"

    # List often cases, with a lot of occurrences, but low confidence
    heavy_cases_limit = 10
    heavy_cases_section = _organize_issues_section(
        named_clusters={key: value for key, value in input_named_clusters.items() if len(value.suggestions) > 20},
        limit=heavy_cases_limit,
        header="Regular cases",
        description="Happen often, require attention.",
    )
    report += heavy_cases_section

    # List interesting cases with not a lot of occurences, but high confidence
    # Issues are sorted by confidendce by default, so we can take the first ones
    interesting_cases_limit = 10
    interesting_cases_section = _organize_issues_section(
        named_clusters={key: value for key, value in input_named_clusters.items() if len(value.suggestions) <= 5},
        limit=interesting_cases_limit,
        header="Rare cases",
        description="Don't happen often, but highly specific.",
    )
    report += interesting_cases_section

    # # Keep topics with at least 5 linked traces
    # if len(cluster.suggestions) < 4:
    #     continue

    # Add stats on how many topics left
    report += "\n\n"
    report += "---\n"
    report += f"*To check another {len(input_named_clusters) - interesting_cases_limit - heavy_cases_limit} issues, ask Alex for the full JSON file.*"
    with open(input_groups_dir_path / "report_25.md", "w") as f:
        f.write(report)
