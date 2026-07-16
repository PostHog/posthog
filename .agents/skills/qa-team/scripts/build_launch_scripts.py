#!/usr/bin/env python3
"""Build the qa-team Workflow launch scripts for a review run.

Usage: python3 build_launch_scripts.py <RUN_DIR>

Reads diff.patch, files.txt, commits.txt, and personas/ from RUN_DIR and writes
launch_first.js and launch_rest.js next to them, with the shared review prompt
JSON-encoded into both. Building the scripts with this tool (instead of having
the orchestrating agent type them) keeps the two prompts byte-identical — the
prompt-cache invariant the launch protocol depends on — and means the diff never
passes through the model as output tokens.
"""

import sys
import json
from pathlib import Path

# Above this size the diff is not inlined into the prompt: agents read it from
# disk instead (paying per-agent ingestion, but keeping requests well-formed).
MAX_EMBED_BYTES = 200_000

PROMPT_TEMPLATE = """You are a code reviewer. Your specific review focus is pre-assigned. Follow these steps exactly:

1. FIRST action — run this exact command with the Bash tool to receive your review focus:

   bash __RUN_DIR__/claim_persona.sh

   It prints your assigned focus, expertise, checklist, and known failure patterns. Conduct your entire review through that lens. Do not read, list, or otherwise inspect anything inside __RUN_DIR__ other than running this command.

2. The code changes to review:

### Changed files

__FILE_LIST__

### Commit messages

__COMMIT_LOG__

### Full diff

__FULL_DIFF__

3. Read the full diff carefully. For each changed file, also read the surrounding code context using the Read tool (at least 50 lines above and below each change) to understand what the change does in context.

4. Apply your assigned review checklist systematically. For each item, determine if the change introduces a risk.

5. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** `file:line` — Description of the issue
  - Why it matters: explanation referencing known failure patterns if applicable
  - Suggestion: specific fix or mitigation

If no findings: "No issues found in my focus area."

**Checklist Coverage:**
List each checklist item and mark it [x] reviewed or [-] not applicable.
(Omit this section if your assigned focus says it has no formal checklist.)

**Summary:**
One paragraph summarizing your overall assessment."""

FIRST_TEMPLATE = """export const meta = {
  name: 'qa-team-launch-first',
  description: 'Launch the first QA reviewer to warm the shared prompt prefix',
  phases: [{ title: 'First reviewer' }],
}
const PROMPT = __PROMPT_JSON__
phase('First reviewer')
const review = await agent(PROMPT, { label: 'reviewer-1', phase: 'First reviewer' })
return { reviews: [review] }
"""

REST_TEMPLATE = """export const meta = {
  name: 'qa-team-launch-rest',
  description: 'Launch the remaining QA reviewers against the warmed prefix',
  phases: [{ title: 'Reviewers' }],
}
const PROMPT = __PROMPT_JSON__
phase('Reviewers')
const reviews = await parallel(
  Array.from({ length: __REST_COUNT__ }, (_, i) => () =>
    agent(PROMPT, { label: `reviewer-${i + 2}`, phase: 'Reviewers' })
  )
)
return { reviews: reviews.filter(Boolean) }
"""


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <RUN_DIR>")
    run_dir = Path(sys.argv[1]).resolve()

    diff = (run_dir / "diff.patch").read_text()
    file_list = (run_dir / "files.txt").read_text().strip()
    commit_log = (run_dir / "commits.txt").read_text().strip()
    reviewer_count = len(list((run_dir / "personas").glob("*.md")))
    if reviewer_count < 2:
        sys.exit("need at least 2 persona files in personas/ before building")

    if len(diff.encode()) > MAX_EMBED_BYTES:
        full_diff = (
            f"The diff is too large to inline. Read it from {run_dir}/diff.patch "
            "with the Read tool (in chunks if needed) before reviewing."
        )
    else:
        full_diff = diff.strip()

    prompt = (
        PROMPT_TEMPLATE.replace("__RUN_DIR__", str(run_dir))
        .replace("__FILE_LIST__", file_list)
        .replace("__COMMIT_LOG__", commit_log)
        .replace("__FULL_DIFF__", full_diff)
    )
    prompt_json = json.dumps(prompt)

    (run_dir / "launch_first.js").write_text(FIRST_TEMPLATE.replace("__PROMPT_JSON__", prompt_json))
    (run_dir / "launch_rest.js").write_text(
        REST_TEMPLATE.replace("__PROMPT_JSON__", prompt_json).replace("__REST_COUNT__", str(reviewer_count - 1))
    )
    sys.stdout.write(f"built {run_dir}/launch_first.js and {run_dir}/launch_rest.js for {reviewer_count} reviewers\n")


if __name__ == "__main__":
    main()
