import json
from pathlib import Path
from typing import Any


def convert_patterns_to_markdown(json_data: dict[str, Any], session_ids_file_path: str, domain: str) -> str:
    """
    Convert EnrichedSessionGroupSummaryPatternsList JSON data to markdown format.

    Args:
        json_data: Dictionary containing patterns data
        session_ids_file_path: Path to session_ids_processed.json file
        domain: Domain name for the report title

    Returns:
        Formatted markdown string
    """
    patterns = json_data.get("patterns", [])

    if not patterns:
        return f"# Session Summaries Report - {domain}\n\nNo patterns found."

    # Load total sessions count
    with open(session_ids_file_path) as f:
        session_ids = json.load(f)
    total_sessions = len(session_ids)

    # Sort patterns by severity: critical, medium, high
    # TODO: Implement in actual summary also
    severity_order = {"critical": 0, "high": 1, "medium": 2}
    patterns.sort(key=lambda p: severity_order.get(p["severity"]))

    markdown_lines = [f"# Session Summaries Report - {domain}", ""]

    # Add issues to review summary
    severity_icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
    }
    session_text = "session" if total_sessions == 1 else "sessions"
    markdown_lines.extend([f"## 📊 Issues to review ({total_sessions} {session_text} scope)", ""])
    markdown_lines.extend(["| Pattern | Severity | Sessions | Failure Rate |"])
    markdown_lines.extend(["|---------|----------|----------|--------------|"])

    for pattern in patterns:
        stats = pattern["stats"]
        sessions_affected = stats["sessions_affected"]
        sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
        failure_percentage = f"{(1 - stats['segments_success_ratio']) * 100:.0f}%"
        severity_icon = severity_icons.get(pattern["severity"], "")

        markdown_lines.append(
            f"| {pattern['pattern_name']} | {severity_icon} {pattern['severity']} | "
            f"{sessions_percentage} ({sessions_affected}) | {failure_percentage} |"
        )

    for pattern in patterns:
        # Pattern header
        markdown_lines.extend(
            [
                "",
                f"## {pattern['pattern_name']}",
                "",
                pattern["pattern_description"],
                "",
            ]
        )

        # Pattern stats
        stats = pattern["stats"]
        sessions_affected = stats["sessions_affected"]
        sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
        success_percentage = f"{stats['segments_success_ratio'] * 100:.0f}%"
        success_count = int(stats["segments_success_ratio"] * stats["occurences"])

        markdown_lines.extend(
            [
                f"**How severe it is:** {pattern['severity'][0].upper()}{pattern['severity'][1:]}",
                "",
                f"**How many sessions affected:** {sessions_percentage} ({sessions_affected} out of {total_sessions})",
                "",
                f"**How often user succeeds, despite the pattern:** {success_percentage} ({success_count} out of {stats['occurences']})",
                "",
            ]
        )

        # Right after pattern description
        markdown_lines.extend(
            [
                "🔍 **How we detect this:**",
            ]
        )
        for indicator in pattern.get("indicators", []):
            markdown_lines.append(f"- {indicator}")
        markdown_lines.append("")

        markdown_lines.extend(
            [
                "### Examples",
                "",
            ]
        )

        # Events examples
        events_to_show = pattern["events"][:3]  # Limit to 3 examples
        total_events = len(pattern["events"])

        for event_data in events_to_show:
            session_id = event_data["target_event"]["session_id"]

            markdown_lines.extend(
                [
                    f"#### Session {session_id}",
                    "",
                    "##### Quick summary",
                    "",
                    f"- **What user was doing:** {event_data['segment_name']}",
                    f"- **What confirmed the pattern:** {event_data['target_event']['description']}",
                    f"- **Where it happened:** {event_data['target_event']['current_url']}",
                    "",
                    "##### Outcome",
                    "",
                ]
            )

            # What happened before
            if event_data["previous_events_in_segment"]:
                markdown_lines.append("- **What happened before:**")
                for prev_event in event_data["previous_events_in_segment"]:
                    markdown_lines.append(f"    - {prev_event['description']}")
            else:
                markdown_lines.append("- **What happened before:** Nothing, start of the segment")

            # What happened after
            if event_data["next_events_in_segment"]:
                markdown_lines.append("- **What happened after:**")
                for next_event in event_data["next_events_in_segment"]:
                    markdown_lines.append(f"    - {next_event['description']}")
            else:
                markdown_lines.append("- **What happened after:** Nothing, end of the segment")

            # Outcome
            outcome_status = "Success" if event_data["segment_success"] else "Failure"
            markdown_lines.extend(
                [
                    f"- **What's the outcome:** {outcome_status}. {event_data['segment_outcome']}",
                    "",
                ]
            )

        # Add note about remaining examples if there are more than 3
        if total_events > 3:
            remaining_examples = total_events - 3
            markdown_lines.extend(
                [
                    "---",
                    "",
                    f"*📋 {len(events_to_show)} examples covered, you can research {remaining_examples} remaining examples at PostHog.com*",
                    "",
                ]
            )

        # Add extra spacing between patterns (except for the last pattern)
        if pattern != patterns[-1]:
            markdown_lines.extend(
                [
                    "",
                    "&nbsp;",
                    "",
                ]
            )

    return "\n".join(markdown_lines)


def save_patterns_to_markdown(
    json_file_path: str, session_ids_file_path: str, domain: str, output_file_path: str | None = None
) -> str:
    """
    Load JSON patterns file and save as markdown.

    Args:
        json_file_path: Path to the JSON file containing patterns
        session_ids_file_path: Path to session_ids_processed.json file
        domain: Domain name for the report title
        output_file_path: Optional path for output markdown file

    Returns:
        Path to the created markdown file
    """
    # Load JSON data
    with open(json_file_path) as f:
        json_data = json.load(f)

    # Convert to markdown
    markdown_content = convert_patterns_to_markdown(json_data, session_ids_file_path, domain)

    # Determine output path
    if output_file_path is None:
        json_path = Path(json_file_path)
        output_file_path = str(json_path.with_suffix(".md"))

    # Save markdown file
    with open(output_file_path, "w") as f:
        f.write(markdown_content)

    return str(output_file_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        sys.exit(1)

    json_file = sys.argv[1]
    session_ids_file = sys.argv[2]
    domain = sys.argv[3]
    output_file = sys.argv[4] if len(sys.argv) > 4 else None

    try:
        result_path = save_patterns_to_markdown(json_file, session_ids_file, domain, output_file)
    except Exception:
        sys.exit(1)
