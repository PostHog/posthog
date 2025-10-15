#!/usr/bin/env python3
"""
Share Claude Code session logs to PostHog/claude-sessions repository.
"""

# ruff: noqa: T201
import sys
import json
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path


def get_project_slug():
    """Get the current project directory slug."""
    cwd = Path.cwd()
    return str(cwd).replace("/", "-").lstrip("-")


def find_latest_session_log(project_slug):
    """Find the most recent session log for the current project."""
    logs_dir = Path.home() / ".claude" / "projects" / f"-{project_slug}"

    if not logs_dir.exists():
        print(f"Error: No Claude Code session logs found for project: {project_slug}")
        print(f"Checked: {logs_dir}")
        sys.exit(1)

    log_files = sorted(logs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not log_files:
        print(f"Error: No session log files found in {logs_dir}")
        sys.exit(1)

    return log_files[0]


def parse_session_log(log_file):
    """Parse JSONL session log and convert to structured data."""
    messages = []

    with open(log_file) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                entry_type = entry.get("type")

                if entry_type == "user":
                    content = entry.get("message", {}).get("content")
                    if isinstance(content, str):
                        messages.append({"type": "user", "content": content})

                elif entry_type == "assistant":
                    content_items = entry.get("message", {}).get("content", [])
                    if isinstance(content_items, list):
                        for item in content_items:
                            if item.get("type") == "text":
                                messages.append({"type": "assistant", "content": item.get("text", "")})
                            elif item.get("type") == "tool_use":
                                messages.append(
                                    {"type": "tool_use", "name": item.get("name"), "input": item.get("input")}
                                )
            except json.JSONDecodeError:
                continue

    return messages


def generate_markdown(messages, session_date, description):
    """Generate markdown content from parsed messages."""
    lines = ["# Claude Code Session\n", f"**Date**: {session_date}\n", f"**Description**: {description}\n", "\n---\n\n"]

    for msg in messages:
        if msg["type"] == "user":
            lines.append("\n## User\n\n")
            lines.append(msg["content"] + "\n")

        elif msg["type"] == "assistant":
            lines.append("\n## Assistant\n\n")
            lines.append(msg["content"] + "\n")

        elif msg["type"] == "tool_use":
            lines.append(f"\n### Tool: `{msg['name']}`\n\n")
            lines.append("```json\n")
            lines.append(json.dumps(msg["input"], indent=2) + "\n")
            lines.append("```\n")

    return "".join(lines)


def sanitize_description(description):
    """Sanitize description for use in filename."""
    sanitized = description.replace(" ", "-")
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
    return sanitized[:50]


def get_github_username():
    """Get the current GitHub username using gh CLI."""
    try:
        result = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Failed to get GitHub username. Make sure you're authenticated with gh.")
        sys.exit(1)


def share_session(markdown_content, description, username):
    """Clone repo, add session, commit and push."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_desc = sanitize_description(description)
    filename = f"{timestamp}-{safe_desc}.md"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Clone the repository
        print("Cloning PostHog/claude-sessions...")
        try:
            subprocess.run(
                ["gh", "repo", "clone", "PostHog/claude-sessions"], cwd=temp_path, capture_output=True, check=True
            )
        except subprocess.CalledProcessError:
            print("Error: Failed to clone PostHog/claude-sessions. Make sure you have access to the repo.")
            sys.exit(1)

        repo_path = temp_path / "claude-sessions"
        user_dir = repo_path / "sessions" / username
        user_dir.mkdir(parents=True, exist_ok=True)

        # Write the markdown file
        session_file = user_dir / filename
        session_file.write_text(markdown_content)

        # Git operations
        try:
            subprocess.run(["git", "add", f"sessions/{username}/{filename}"], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"Add Claude Code session: {description}\n\nAuthor: {username}"],
                cwd=repo_path,
                check=True,
            )
            subprocess.run(["git", "push", "origin", "main"], cwd=repo_path, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error: Git operation failed: {e}")
            sys.exit(1)

        session_url = f"https://github.com/PostHog/claude-sessions/blob/main/sessions/{username}/{filename}"
        return session_url


def main():
    """Main entry point."""
    # Get description from command line args
    description = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

    # Find the session log
    project_slug = get_project_slug()
    log_file = find_latest_session_log(project_slug)
    print(f"Found session log: {log_file}")

    # Get session date
    session_date = datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    # Set default description if not provided
    if not description:
        description = f"Claude Code Session - {session_date}"

    print("Converting session log to markdown...")
    messages = parse_session_log(log_file)
    markdown_content = generate_markdown(messages, session_date, description)

    print("Saving session to PostHog/claude-sessions repo...")
    username = get_github_username()
    print(f"Using GitHub username: {username}")

    session_url = share_session(markdown_content, description, username)

    print()
    print("✓ Session log saved to PostHog/claude-sessions!")
    print(f"URL: {session_url}")
    print()


if __name__ == "__main__":
    main()
