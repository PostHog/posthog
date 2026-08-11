#!/usr/bin/env python3
"""Put back snapshot blocks a test shard deleted without ever exercising them.

syrupy removes every snapshot it considers unused whenever ``--snapshot-update``
is on, and it skips that step only when the session deselected at least one item
(``SnapshotReport.selected_all_collected_items``). A shard that happens to select
everything it collected therefore deletes snapshots owned by legs it never ran:
``[new_events_schema]`` variants, materialized-column and persons-on-events cases,
anything asserted behind a condition. The shard cannot tell those apart from
genuinely obsolete ones, so the bot commit should never carry a deletion at all.

Repairing against HEAD keeps hand-pruned snapshots pruned: a block a human deleted
is already absent from HEAD, so only blocks this run removed come back.
"""

from __future__ import annotations

import sys
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

NAME_PREFIX = "# name: "
DIVIDER = "# ---"
NAMES_SHOWN_PER_FILE = 5


def split_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Split an .ambr file into its header and one verbatim block per snapshot name."""
    header: list[str] = []
    blocks: dict[str, str] = {}
    name: str | None = None
    body: list[str] = []

    for line in text.splitlines(keepends=True):
        if name is None:
            if line.startswith(NAME_PREFIX):
                name = line[len(NAME_PREFIX) :].rstrip("\n")
                body = [line]
            else:
                header.append(line)
            continue
        body.append(line)
        if line.rstrip("\n") == DIVIDER:
            blocks[name] = "".join(body)
            name = None

    return "".join(header), blocks


def repair(head_text: str, worktree_text: str) -> tuple[str, list[str]] | None:
    """Return the repaired file and the names it restored, or None if nothing was deleted."""
    head_header, head_blocks = split_blocks(head_text)
    worktree_header, worktree_blocks = split_blocks(worktree_text)

    restored = sorted(name for name in head_blocks if name not in worktree_blocks)
    if not restored:
        return None

    merged = dict(worktree_blocks)
    for name in restored:
        merged[name] = head_blocks[name]

    # syrupy writes blocks sorted by name, so a repaired file stays byte-identical to
    # what the next update-mode run produces and never shows up as spurious churn.
    header = worktree_header or head_header
    return header + "".join(merged[name] for name in sorted(merged)), restored


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main() -> int:
    changed = _git("diff", "--name-only", "--diff-filter=MD", "HEAD", "--", "*.ambr").split()
    total = 0

    for path in changed:
        target = Path(path)
        result = repair(_git("show", f"HEAD:{path}"), target.read_text(encoding="utf-8") if target.exists() else "")
        if result is None:
            continue

        text, restored = result
        target.write_text(text, encoding="utf-8", newline="\n")
        total += len(restored)
        shown = ", ".join(restored[:NAMES_SHOWN_PER_FILE])
        more = f" (+{len(restored) - NAMES_SHOWN_PER_FILE} more)" if len(restored) > NAMES_SHOWN_PER_FILE else ""
        logger.info("%s: restored %d snapshot(s): %s%s", path, len(restored), shown, more)

    if total:
        logger.info("::notice::Restored %d snapshot(s) this shard deleted without exercising them.", total)
    else:
        logger.info("No deleted snapshots to restore.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
