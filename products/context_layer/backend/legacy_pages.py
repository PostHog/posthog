import re
from pathlib import Path

from products.context_layer.backend import repo_lint
from products.context_layer.backend.store import LintFailedError


def migrate_legacy_channel_pages(root: Path, team_ids_by_channel: dict[str, int]) -> list[str]:
    legacy = root / "channels"
    if not legacy.exists() and not legacy.is_symlink():
        return []
    if legacy.is_symlink() or not legacy.is_dir():
        raise LintFailedError(["channels: expected a directory of Space pages"])

    moves: dict[Path, Path] = {}
    contents: dict[Path, str] = {}
    links: dict[str, str] = {}
    for source in sorted(legacy.iterdir()):
        if source.is_symlink() or not source.is_file() or source.suffix != ".md":
            raise LintFailedError([f"{source.relative_to(root)}: cannot migrate this entry automatically"])
        fields = repo_lint._frontmatter(source)
        if "channel_id" not in fields:
            raise LintFailedError([f"{source.relative_to(root)}: channel_id is required"])
        channel_id = fields["channel_id"].strip("\"'")
        team_id = team_ids_by_channel.get(channel_id)
        if team_id is None:
            raise LintFailedError([f"{source.relative_to(root)}: no public Space matches this channel_id"])
        destination = root / "projects" / str(team_id) / "spaces" / source.name
        if any(
            path.is_symlink()
            for path in [root / "projects", destination.parent.parent, destination.parent, destination]
        ):
            raise LintFailedError([f"{destination.relative_to(root)}: migration cannot write through a symlink"])
        if destination.exists():
            raise LintFailedError([f"{destination.relative_to(root)}: resolve the existing page before migration"])
        content = source.read_text(encoding="utf-8")
        if "team_id" in fields:
            if fields["team_id"] != str(team_id):
                raise LintFailedError([f"{source.relative_to(root)}: team_id does not match the Space"])
        else:
            content = content.replace("---\n", f"---\nteam_id: {team_id}\n", 1)
        moves[source] = destination
        contents[source] = content
        links[str(source.relative_to(root).with_suffix(""))] = str(destination.relative_to(root).with_suffix(""))

    def rewrite_link(match: re.Match[str]) -> str:
        target = match.group(1)
        path = target.split("|", 1)[0].split("#", 1)[0]
        replacement = links.get(path.removesuffix(".md"))
        return match.group(0) if replacement is None else f"[[{replacement}{target[len(path) :]}]]"

    changed: list[str] = []
    for source, destination in moves.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents[source], encoding="utf-8")
        source.unlink()
        changed.extend([str(source.relative_to(root)), str(destination.relative_to(root))])
    legacy.rmdir()
    for directory in repo_lint.MARKDOWN_DIRECTORIES:
        if (root / directory).is_symlink():
            continue
        for page in (root / directory).rglob("*.md"):
            if page.is_symlink() or not page.is_file():
                continue
            content = page.read_text(encoding="utf-8")
            updated = repo_lint.WIKILINK_RE.sub(rewrite_link, content)
            if updated != content:
                page.write_text(updated, encoding="utf-8")
                changed.append(str(page.relative_to(root)))
    return sorted(set(changed))
