# Duplication lint

Run `python3 bin/lint_duplication.py --base origin/master` to check for new Python and TypeScript duplication.
The check compares the branch's committed `HEAD` with its merge base.
It ignores uncommitted and untracked files.

A reported pair must include at least one changed file to count as new duplication.
Removing a third copy can make the scanner pair two unchanged files differently, which must not fail the check.
For pairs that include a changed file, the check still compares the fragment and its occurrence count with the baseline.

The thresholds are in `bin/lint-duplication.limits.json`.
When a new pair exceeds its threshold, extract the shared code into a helper.
