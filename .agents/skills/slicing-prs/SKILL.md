---
name: slicing-prs
description: >
  Decides how to slice a change into PostHog PRs before building or opening them —
  auto-approval track vs human review track, when to stack vs collapse into one PR,
  quarantining deny-listed files (dependencies, migrations, workflows) into their own
  PRs, and validating direction with the DRI before large speculative builds. Use
  when planning a feature's PR structure, splitting a large diff, opening a stack,
  or asking "should this be one PR or several?".
---

# Slicing PRs

A large share of never-merged PRs die to structure, not content: stacks that get collapsed because reviewers wanted one PR, fragments split purely to duck a size limit, and fully-built features abandoned when priorities shift.
Slice deliberately up front instead of restructuring under review.

## Rule 1 — aim every PR at the auto-approval track

A PR stamphog can take merges in about an hour; one that needs a human commonly waits half a day to several days.
Stampable means: ≤500 changed lines, ≤20 files, no deny-category files or title words (auth, billing, migrations, lockfiles/deps, `.github/workflows`, openapi/swagger — full list in `getting-prs-approved`), not a draft, no confirmed bot findings.

## Rule 2 — don't over-split

Splitting below the size reviewers actually consume creates pure overhead: coupled fragments get re-assembled into one PR anyway, and each fragment pays its own CI, regeneration, and rebase tax.

- One coherent feature under 500 lines → **one PR**, even if it has several conceptual parts.
- Split only along **independently shippable seams** — each PR must be mergeable and revertable alone, with a one-line purpose a reviewer understands without reading the sibling PRs.
- Never split purely to duck the size ceiling; a 600-line coherent change on the human track beats two coupled 300-line PRs that must land together.

## Rule 3 — quarantine deny-listed files

Lockfile or dependency bumps, Django/ClickHouse migrations, and workflow edits each force everything sharing their PR onto the human track:

- dependency bump → standalone PR (human-track regardless; keep it minimal with one line of intent)
- migration → standalone PR when possible; the Backend CI migration analyzer can clear safe migrations for stamphog, but only when the rest of the PR passes the other gates
- feature code → stampable PR(s) referencing the above

## Rule 4 — stacks: shallow, land-as-you-go

Deep stacks rot: bottom layers wait on review while upper layers accumulate rebases, migration-number collisions, and invalidated regenerated artifacts.

- Keep roughly **three live layers maximum**; land the bottom before cutting a fourth.
- Make each layer independently stampable when possible — a stack where every layer needs a human serializes days of latency.
- Regenerate artifacts (OpenAPI types, snapshots) only on the layer about to merge — see `preflighting-pushes`.
- Migrations go in the bottom layer or their own PR; expect renumbering at land time.
- Delete local branches as layers land — see `sweeping-open-prs`.

## Rule 5 — DRI check before speculative builds

Fully-built multi-PR features abandoned as drafts are a recurring failure mode; the validation happened at PR time instead of before build time.
Before building anything that will exceed roughly two PRs or a thousand lines:

1. Write five lines: problem, approach, expected PR plan (count, rough sizes, which need human review).
2. Get an explicit go-ahead from the DRI or owning team.
3. Only then build. If the answer is "not now", file the five lines as an issue and move on — that is the cheap version of an abandoned ten-PR stack.

## Rule 6 — plan human-track PRs around reviewer availability

Any PR that will need a human (sibling repos without stamphog, migrations, cross-team files): open it early in your overlap window with reviewers, name a reviewer, and pre-announce anything that lands late in your day — per the `getting-prs-approved` ladder.
