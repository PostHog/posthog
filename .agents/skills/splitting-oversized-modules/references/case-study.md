# Case study: splitting `visual_review`'s `logic.py`

The worked example this skill is derived from. Useful as a reference for what a
finished layout looks like and what the payoff actually measures out to.

Prompted by Martin Fowler's
[The Economic Benefit of Refactoring](https://martinfowler.com/articles/exploring-gen-ai/refactoring-economic-benefit.html),
which measures the same thing on a Rust Firestore layer and lands on an 83% input
token reduction. This split reproduced that result on a Django product, which
suggests the effect is about file size and cohesion rather than anything
language-specific.

## Before

| file                          | lines | tokens |
| ----------------------------- | ----- | ------ |
| `backend/logic.py`            | 2951  | 26,319 |
| `backend/tests/test_logic.py` | 3000  | 26,608 |

Any behavior change in the product started with ~53k input tokens of reading. The
file held ten concerns: repo CRUD, artifacts, run lifecycle, baseline resolution,
GitHub HTTP, commit statuses, PR comment rendering, PR comment posting, quarantine,
and a 309-line overview aggregate.

## After

19 modules in `backend/logic/`, largest 420 lines, mirrored by 12 files in
`backend/tests/logic/`.

The dependency graph came out acyclic on the first attempt only after pulling run
lookups out of the lifecycle module:

```text
errors  artifacts  comment_markdown          (leaves)
repos   run_queries  github_api              (leaves + errors)
baselines      <- github_api, run_queries
ci_status      <- github_api, comment_markdown
comments       <- github_api, comment_markdown, run_queries
gating         <- baselines, ci_status, comments, comment_markdown
uploads        <- artifacts, run_queries
runs           <- everything above
approvals      <- run_queries, baselines, ci_status, gating
thumbnails  history  snapshot_diffs  toleration  quarantine  baseline_overview
```

`run_queries` exists because `runs` (lifecycle) and `uploads` (upload verification)
both needed run lookups and would otherwise import each other. Splitting reads from
writes removed the cycle without a deferred import.

`snapshots` was the first name for what became `thumbnails`, `history`,
`snapshot_diffs`, and `toleration` — it collided with local variables named
`snapshots` in two places. The collision forced a finer split that was better anyway.

## Measured read-set

| representative change                      | before | after | saved |
| ------------------------------------------ | ------ | ----- | ----- |
| Add a line to the PR review-prompt comment | 52,927 | 8,784 | 83%   |
| Change baseline healing across a rebase    | 52,927 | 9,720 | 82%   |
| Add a quarantine expiry rule               | 52,927 | 1,794 | 97%   |
| Change what greens the CI gate             | 52,927 | 8,249 | 84%   |
| Add a field to run creation                | 52,927 | 9,902 | 81%   |

Total code grew ~5% from the import header each new module carries. That is the
signature of a move rather than a rewrite — the article's LOC stayed flat for the same
reason.

## What verification caught

- **`ruff`**, immediately: the `snapshots` module name shadowed local variables
  (`F811`/`F823`), and `logger` was missing from six modules (`F821`) because it sat
  past the header boundary.
- **Standalone imports** of each module, in both directions: confirmed no cycles
  survived. Import order matters; a cycle can hide behind one entry point.
- **Patch-target resolution**: all 108 patch targets across the test tree resolved
  after retargeting. Roughly 40 needed changing, and a misdirected one would have
  passed silently.
- **Definition equivalence**: 111 definitions and 18 test classes / 137 test methods
  compared identical modulo module qualification.

The equivalence check is what made the change reviewable. A 48-file, ±6k-line diff
is not readable line by line; "every definition is byte-identical apart from
qualification, and here is the script that checks it" is.

## Ordering that worked

Measure → map → assign (draw the graph) → script the move → `ruff --fix` → retarget
callers and patches → split tests the same way → verify equivalence → cleanup →
suite. Cleanup last, and re-verify after it: dropping dead `if TYPE_CHECKING: pass`
blocks and stale section comments is still a change to files you just claimed were
unchanged.
