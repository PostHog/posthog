---
name: writing-code-comments
description: >
  Gates whether a code comment should exist and forces the ones that stay to explain why, not what.
  Use ALWAYS before writing or editing a comment in any language (Python, TypeScript, Go, Rust, SQL), and when reviewing a diff that adds comments.
  Removes the comment types that clutter the codebase: narration that restates the code, change-history and chat-context notes ("previously did X", "per PR #123", "AI:"), commented-out code, and redundant docstrings.
  Keeps the ones that earn their place: a non-obvious why, a warning about a non-local consequence, a pointer to context a future reader can't reconstruct.
  Not for user-facing copy (see `/writing-user-facing-copy`) or commit messages.
---

# Writing code comments

Run this before adding or editing any comment. The default is no comment. Good code with clear names carries most of its meaning on its own; a comment earns its place only when it tells a reader something the code cannot.

## The gate: one question

Before writing a comment, answer:

> **What does this tell a future reader that the code itself doesn't?**

If the answer is "it restates what the code does", delete it. Rename the variable or extract a function instead.

A comment worth keeping answers a *why* the code can't:

- ✅ `# ATOMIC_REQUESTS is off, so wrap the two writes that must commit together`
- ✅ `// Stripe sends the amount in cents; the rest of our system uses dollars`
- ✅ `# Kept in sync with the enum in migrations/0042; update both`

## Delete these

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

Write comments the way you'd write technical documentation: explicit, complete, and precise. State the reasoning in full so the reader does not have to infer any of it. A longer comment that spells out the cause and effect is better than a short one that leaves parts implicit.

- **Be explicit and technical.** State the cause and effect in full. Name the actual conditions, values, and consequences. A reader should not have to reconstruct your reasoning from a hint.
- **Complete sentences, not fragments.** Write "Feature X does Y because Z, so callers must W." Don't compress it into a clipped fragment.
- **Longer is fine when it adds information.** Prefer one thorough sentence (or two) that fully explains the why over a terse one that only gestures at it. Cut words that add nothing, not words that add precision.
- **No short-punchy-fragment-with-a-dash style.** The clipped `# do the thing — it's faster` shape is the AI tell to avoid. Rewrite it as a full sentence with a real connective ("because", "so that", "which means"), no em-dash.
- **Explain why, not what.** The what is in the code; the why usually is not.
- **Preserve existing comments when moving or refactoring code**, unless the change makes them wrong. Don't drop an existing why just because you're relocating the function.
- **Match the surrounding density.** Don't add a comment to every line of a file that had none; don't strip a well-commented module bare.

Contrast:

- ❌ `# batch here — avoids N+1`
- ✅ `# Fetch all the memberships in one query here because doing it per-row triggers an N+1 against posthog_organizationmembership, which dominated the request time on large orgs.`

## When you're tempted to comment

Try, in order: (1) a better name, (2) a smaller function, (3) a type. Reach for a comment only when none of those can carry the meaning.
