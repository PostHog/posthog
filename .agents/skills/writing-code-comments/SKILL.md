---
name: writing-code-comments
description: >
  Gates whether a code comment should exist and keeps the ones that stay to a one-line note.
  Use ALWAYS before writing or editing a comment in any language (Python, TypeScript, Go, Rust, SQL), and when reviewing a diff that adds comments.
  Removes comments that stand in for work (TODO, FIXME, "for now", "simplified", "does not handle X", suppressions without a cause), paragraph explanations of code that should be restructured instead, narration that restates the code, change-history and chat-context notes ("previously did X", "per PR #123", "AI:"), perishable measurements ("~20 min build", "currently"), commented-out code, and redundant docstrings.
  Keeps a short note that earns its place: a non-obvious why, a warning about a non-local consequence, a pointer to context a future reader can't reconstruct.
  Not for user-facing copy (see `/writing-user-facing-copy`) or commit messages.
---

# Writing code comments

Run this before adding or editing any comment. The default is no comment. Good code with clear names carries its meaning on its own; a comment earns its place only when it tells a reader something the code cannot, in one short note.

A comment is never a substitute for doing the work. When the urge is to explain why the code is awkward, incomplete or wrong, the job is to fix the code, not to describe it.

## The gate: one question

Before writing a comment, answer:

> **What does this tell a future reader that the code itself doesn't?**

If the answer is "it restates what the code does", delete it. Rename the variable or extract a function instead.

A comment worth keeping answers a _why_ the code can't:

- ✅ `# ATOMIC_REQUESTS is off, so wrap the two writes that must commit together`
- ✅ `// Stripe sends the amount in cents; the rest of our system uses dollars`
- ✅ `# Kept in sync with the enum in migrations/0042; update both`

## Delete these

### Comments that stand in for the work

A comment that names a gap, a shortcut or a defect is an admission that the change is not finished. Finish it, or take the unfinished part out of the diff.

- ❌ `// TODO: handle the empty state` / `# FIXME: race when two workers start`
- ❌ `// simplified for now` / `# temporary workaround` / `// HACK`
- ❌ `# in a real implementation this would page through results`
- ❌ `// this does not handle deleted users`
- ❌ `// oxlint-disable-next-line react-hooks/exhaustive-deps` to quiet a real bug. Fix the dependency list or move the effect into a logic.
- ❌ `# type: ignore` or `// @ts-expect-error` over a type the code gets wrong. Fix the type.

A suppression stays only where the tool is wrong, for that one line, with the reason on the same line: `# noqa: PLC0415 keeps the heavy dep off the import path`.

### Explanations that should be code

A paragraph above a block means the block is too hard to read. Rename, extract a function, introduce a type or restructure the branch until the code carries the meaning, then delete the paragraph. Multi-paragraph docstrings and JSDoc blocks that walk through usage belong in a README or a docs page, not in the source.

### Narration that restates the code

- ❌ `# increment the counter` above `counter += 1`
- ❌ `// loop over users` above `for user of users`
- ❌ `# return the result` above `return result`

If a block needs narration to be followed, the fix is smaller functions and better names, not a comment.

### Change history and chat context

Never record how the code got here. That belongs in the commit message and PR description, where it's attached to the diff and searchable. In the source it's noise that goes stale immediately.

- ❌ `# previously used a set here, switched to a list for ordering`
- ❌ `// per PR #1234` / `# as discussed` / `# changed because the old way broke`
- ❌ `# AI: generated this helper` / `// agent: refactored`
- ❌ `# TODO(2024-01): remove after migration` left in long after the migration

### Perishable measurements and current-state stamps

Measured timings, counts, and rates rot silently: nothing forces them to update, and a rotted number misleads the next person sizing a timeout or shard count. The same goes for "currently" / "today" hedges, because the sentence states the same fact without them. State the durable relationship the number stood for.

- ❌ `# skip the ~20 min build` when the durable fact is that the build is expensive
- ❌ `# ci-backend runs ~28m, so 60m ≈ one red result` instead of "sized past a full run of the slowest workflow"
- ❌ `# no story currently opts into webkit snapshots` where dropping "currently" states the same fact
- ❌ `# ~20 minutes in June, past 25 by July` because trend narration is change history

Numbers that stay:

- A dated snapshot: `# as of August 2024, Homebrew ships 4.13.2` (the date makes staleness visible)
- A restated adjacent code literal: `# runs that took >5 min (300 seconds)` beside the `300` (it updates with the code)
- A platform constant: `# GitHub's comment size limit (~64KB)`
- A target or budget: `# Target: ~15 min per shard` (policy, not measurement)
- Cited evidence: `# 30% peak memory observed on 16-core runs (#46853)` (the link dates it)

### Commented-out code

Delete it; the version history has it if it's needed again. Commented-out code is ambiguous to the next reader, who can't tell whether it's a note, a rollback plan, or an accident.

### Redundant docstrings and type restatements

- ❌ A docstring that repeats the function name in prose: `"""Gets the user by id."""` on `get_user_by_id`
- ❌ `# type: string` on an already-typed field
- ❌ Python test doc comments (the repo convention is none; the test name says it)

## Keep these

- A **why** that isn't obvious from the code: a workaround, a performance trade-off, a spec quirk, an ordering constraint.
- A **warning** about a consequence that lives elsewhere: "changing this breaks the cache key", "callers rely on this being sorted".
- A **pointer** to context a reader can't reconstruct from the repo: a link to the spec, ticket, or the reason a surprising value was chosen.

## Style

A comment is a note: one line by default, two at most when a warning needs its consequence spelled out. If it needs more, the code or a doc needs to change instead.

- **State the fact, not the story.** Name the actual condition, value or consequence, so the reader does not have to infer it.
- **Use mostly ASD-STE100 Simplified Technical English.** Use active voice, simple tenses, one idea per sentence, and consistent terms.
- **No em-dash.** The tell to avoid is the clipped two-part phrase joined by a dash, like `# do the thing — it's faster`. Use a real connective instead ("because", "so that", "to avoid").
- **Explain why, not what.** The what is in the code; the why usually is not.
- **Preserve existing comments when moving or refactoring code**, unless the change makes them wrong. Don't drop an existing why just because you're relocating the function.
- **Do not add density.** Don't add a comment to every line of a file that had none, and when you touch an over-commented block, cut it back to notes.

The fix for the em-dash is the connective, not more words:

- ❌ `# batch here — avoids N+1`
- ✅ `# batch here to avoid an N+1 against posthog_organizationmembership`

## When you're tempted to comment

Try, in order: (1) a better name, (2) a smaller function, (3) a type. Reach for a comment only when none of those can carry the meaning.
