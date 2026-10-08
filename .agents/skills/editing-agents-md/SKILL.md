---
name: editing-agents-md
description: >
  Decide whether a rule belongs in an AGENTS.md / CLAUDE.md file, and write it so it holds.
  Use before adding, editing, or removing any instruction in a root or nested AGENTS.md, when a
  convention keeps getting broken and someone proposes documenting it, when reviewing a diff that
  touches one, or when a file has grown and needs a trim. Carries the enforcement-tag convention
  (`[lint: <id>]` / `[review]`), the six configuration smells to check against, and the size budget.
  Trigger terms: AGENTS.md, CLAUDE.md, agent instructions, context file, add a rule, document this
  convention, the file is too long.
---

# Editing AGENTS.md

The root `AGENTS.md` loads in full at the start of every session, in every tool that reads it.
A line you add is paid for by every task in the repo, forever, whether or not that task touches the subject.
So the question is never "is this true?" — it is "is this worth loading into every session?"

Two findings set the frame:

- Adding a context file raises inference cost by over 20% on average, and does not reliably raise task success ([2602.11988](https://arxiv.org/abs/2602.11988)). A second study measured the opposite sign on runtime and tokens ([2601.20404](https://arxiv.org/abs/2601.20404)). The evidence is mixed, which argues for a small sharp file rather than no file.
- File size, instruction position, file architecture, and contradictions between adjacent files each produced **no detectable effect** on whether an agent follows a rule, across 1,650 sessions ([2605.10039](https://arxiv.org/abs/2605.10039)).

Read the second one carefully, because it kills a whole class of proposals.
Moving a section higher "so the agent sees it" is churn against a null result.
Do not reorder for attention. Reorder only when a heading makes a rule easier for a **human** to find or cite.

## 1. Does this belong in the file at all?

Work down this ladder and stop at the first rung that fits. It is the same ladder `AGENTS.md` states for itself.

| Rung | Mechanism                                                    | Use when                                                |
| ---- | ------------------------------------------------------------ | ------------------------------------------------------- |
| 1    | **Linter** — ruff, oxlint, semgrep (`.semgrep/rules/devex/`) | The violation is a code pattern a matcher can see       |
| 2    | **lint-staged / pre-commit**                                 | It needs the file list or the working tree, not the AST |
| 3    | **Skill** (`.agents/skills/`)                                | It applies to one kind of task, not every task          |
| 4    | **A rule in AGENTS.md**                                      | None of the above can carry it                          |

Rung 4 is the last resort, not the default.
A convention that a semgrep rule could catch belongs in `.semgrep/rules/devex/` — read its README for the severity choice and the WARNING-to-ERROR ratchet.
Put the migration playbook in the rule's `message:` field, because that is what an author actually reads when it fires.

Rung 3 is the one people skip most.
If a rule only matters while merging a PR, writing a migration, or building a workflow, it belongs in that skill, where it loads on demand and can be ten times longer.

## 2. Check the six smells

Measured across 100 popular repositories ([2606.15828](https://arxiv.org/abs/2606.15828)). Prevalence in brackets.

- **Lint leakage [62%]** — the rule restates what a linter already blocks. This is the most common failure by a wide margin. Do not delete the reasoning, but cut it to the reason plus the rule id, and tag it. CI is the check; the prose is only the why.
- **Context bloat [42%]** — content that does not apply to most sessions. Environment-specific setup, product documentation, anything a `docs/` page should hold. Target is under 200 lines.
- **Skill leakage [35%]** — task-specific instructions sitting in the always-loaded file instead of a skill.
- **Conflicting instructions [28%]** — two rules that disagree, often because one aged. Grep for the other statement before you add yours.
- **Init fossilization [24%]** — text nobody has reviewed since it was generated. If you are editing near a stale rule, verify it still holds and fix it in the same diff.
- **Blind references [16%]** — a link with no statement of what it holds and when to read it. Every link needs a "read this when …" clause, or an agent has no basis to spend a tool call on it.

## 3. Write the rule as an invariant, not an instruction

The file is read by authors and reviewers alike. An invariant serves both; an instruction has to be translated.

- Say what must be true: "Every tenant-data model must have `team_id`."
- Not what to do: "Remember to add `team_id` when you make a model."

Be specific and imperative. A vague preference changes nothing.
"Use `uv pip`, never `pip`" works. "We prefer uv" does not.
Name the trigger the rule fires on, so a reader scanning a diff knows when it applies.

Keep to the repo's prose conventions: ASD-STE100 Simplified Technical English, active voice, one idea per sentence, semantic line breaks, American English.

## 4. Tag what enforces it

Every rule in **Architecture guidelines** and **Code Style** carries a tag. Extend the convention when you add to those sections.

```markdown
- **Do not use `Team` or `Organization` rows as mutexes.** `[lint: hot-parent-row-select-for-update]` PostgreSQL takes …
- **There is no implicit per-request transaction.** `[review]` PostHog does not enable `ATOMIC_REQUESTS` …
```

- `[lint: <id>]` — a semgrep rule id, a `ruff <CODE>`, or an invariant test filename. A reviewer skips it, because CI is the gate.
- `[review]` — nothing catches this. A reader is the only control, so it earns its place in the file.

Every rule in those two sections carries one of the two tags, and every tag must resolve against the repo.
`posthog/test/repo_invariants/test_agents_md_enforcement_tags.py` fails the build on an untagged rule, and on a `[lint: …]` that names a rule, code, or file which no longer enforces anything.
A ruff code moved to the `ignore` list stops counting, so a tag cannot survive its rule being switched off.
That is the point: a stale tag is worse than no tag, because a reviewer trusts it and skips the check.
When a tag names a command or a CI job rather than a single rule id, add it to `FREE_FORM` in that test — deliberately, not to silence a typo.

A rule that stays `[review]` for a long time is a candidate for rung 1. That visibility is half the reason the tags exist.

## 5. Root or nested?

Both files get the same smells check. The budget differs.

**Root `AGENTS.md`** — loads every session, in every tool, for every task. Strict. A rule earns its place only if it applies across the repo, or if getting it wrong is expensive and nothing catches it (the public-repo rules are the model). Keep the enforcement tags current.

**Nested `AGENTS.md`** (about 27 of them: `posthog/temporal/`, `rust/`, `frontend/src/`, most of `products/`) — loads when an agent works in that subtree, so a local convention is cheap here and expensive in the root. Move a directory-specific rule down rather than up. No tag convention required, though it does no harm.

Never state the same rule in both. That is how conflicting instructions start.

## 6. Before you commit

- The rule is on rung 4 because rungs 1 to 3 genuinely do not fit.
- It reads as an invariant, with a trigger a reader can spot in a diff.
- It is tagged, if it sits in Architecture guidelines or Code Style.
- No other line in the file, or in a nested `AGENTS.md`, says something different.
- Every link you added says when to read it.
- Every link and skill reference resolves:

```sh
grep -oE '\]\(([a-zA-Z0-9_./-]+\.md[^)]*)\)' AGENTS.md | sed 's/](//;s/)$//;s/#.*//' | sort -u \
  | while read -r f; do [ -e "$f" ] || echo "MISSING: $f"; done

hogli test posthog/test/repo_invariants/test_agents_md_enforcement_tags.py
```

- The file got shorter, or you can say what the added characters buy every session in the repo.
