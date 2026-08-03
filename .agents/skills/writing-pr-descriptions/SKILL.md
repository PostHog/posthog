---
name: writing-pr-descriptions
description: >
  Sets the writing style for the body of a pull request description: one fact per bullet, short sentences, active voice, no idioms.
  Use ALWAYS before writing or editing a PR description, and when rewriting one a reviewer found hard to follow.
  Adapted from the ASD-STE100 Simplified Technical English writing rules, which exist so a reader under time pressure, often in a second language, can check each statement on its own.
  Covers the eight rules, how they apply per template section, and a worked before/after on a merged PR.
  Applies to prose only: tables, mermaid diagrams, code blocks, alerts and links are out of scope and must be left alone.
  Not for the PR title (see the conventional-commit rules in AGENTS.md), commit messages, code comments (see `/writing-code-comments`), or product copy (see `/writing-user-facing-copy`).
---

# Writing PR descriptions

The structure comes from `.github/pull_request_template.md`. This skill is about the sentences inside it.

A reviewer reads a description to decide whether a change is correct. They scan, they stop, they check one claim, they move on.
A sentence that packs four facts into three clauses forces them to hold all four before any of them can be checked.
Split it, and each line stands on its own.

## The eight rules

1. **One fact per bullet.** If a sentence joins two facts with "so", "which", ";" or a comma splice, it is two bullets.
2. **Under 25 words per sentence.** Under 20 in Problem and Changes.
3. **Active voice, with a stated subject.** "The builder used the first entry", not "the first entry was used".
4. **Simple tenses.** Past, present, future. No perfect or progressive forms.
5. **No `-ing` verb forms where a simple tense works.** "An audit found this defect", not "found this while auditing". Technical names keep theirs (`sharding plan`, `logging config`).
6. **Keep the articles and prepositions.** "The job downloads the artifact", not "job downloads artifact". Unstack possessives: "the key from the subdirectory layout", not "the subdirectory layout's".
7. **One word per thing, every time.** Pick `shard`, `job` or `run` and never vary it for style. Define an abbreviation on first use, then use it.
8. **No idioms, no jokes, no understatement.** They cost a reader who does not share your context, and they are the first thing to fail in translation.

## Prose only

Do not touch tables, mermaid diagrams, fenced code, alerts (`> [!NOTE]`) or links.
They carry roughly a quarter of a typical description here and they are already the fastest part to scan.
Compressing evidence into a table is still the right move, and a table cell is not a sentence.

## Per section

- **Problem.** The causal chain, one step per bullet, in order. State the effect last. This section gains the most from the rules.
- **Changes.** What the change does, in the present tense. Not how you arrived at it.
- **How did you test this code?** One bullet per check, each with its result. Name what you did not run.
- **Agent context.** Same rules. Decisions and rejected options, not a session log.

## Worked example

From [fix(ci): recover jest shard identity in flat junit downloads](https://github.com/PostHog/posthog/pull/74003).

Before, one sentence, 25 words, five facts:

> When the signals job's artifact glob matches one artifact (every selective-mode run), `download-artifact` extracts it flat, so spans get `job_key junit-artifacts:junit-artifacts:None` and re-run recovery joins miss.

After:

> - The signals job downloads the JUnit artifacts with a glob pattern.
> - In selective mode, the pattern matches only one artifact.
> - Then the `download-artifact` action extracts the files flat.
> - The trace span gets the job key `junit-artifacts:junit-artifacts:None`.
> - The re-run recovery cannot join on this key.

Longer by 40%, and each line is checkable on its own.
That trade is the point: a description is read more often than it is written.

## What you lose

Be honest about it rather than fighting it.
A good one-line opener like "a push to master linked to a stranger's PR" has no form under these rules.
Neither does a clause whose job is to convey that something matters.
Where the stakes are the point, state them as a fact: "the CI-breakage skill reads that table to find the pull request that made master red."

## Before you publish

- Every bullet holds one fact.
- No sentence runs past 25 words.
- No `-ing` verb form that a simple tense would carry.
- The same thing is named the same way throughout.
- Tables, diagrams and code blocks are untouched.

Background, measurements on 60 merged PRs, and full before/after descriptions: [docs/internal/pr-description-voice-ste.md](../../../docs/internal/pr-description-voice-ste.md).
