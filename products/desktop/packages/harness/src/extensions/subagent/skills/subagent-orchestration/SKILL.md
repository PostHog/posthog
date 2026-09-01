---
name: subagent-orchestration
description: How and when to delegate work to subagents via the `subagent` tool (Explore, Plan, General). Use when a task involves codebase recon, implementation planning, or actual code changes that would benefit from an isolated context window instead of doing it all inline.
---

# Subagent Orchestration

You (the parent session) can delegate scoped work to focused subagents, each running in
its own isolated pi process with its own context window. Use this to keep your own
context clean and to parallelize independent work.

## When to delegate

Delegate when a piece of work is:
- **Self-contained**: it doesn't need your full conversation history, just a task and
  some context you can state explicitly.
- **Isolable**: it would otherwise burn a lot of your context window (e.g. broad codebase
  search, reading many files) for a result you can summarize down to a few paragraphs.
- **Parallelizable**: several independent instances of it can run at once (e.g. exploring
  two unrelated areas of a large codebase in the same turn).

Do not delegate trivial one-line changes, or work that fundamentally needs your full
conversation context to do correctly — that's what `context` (below) is for, but if
almost everything is relevant, delegation adds overhead for no benefit.

## Bundled agents

| Agent | Use for | Tools | Model | Notes |
|-------|---------|-------|-------|-------|
| `Explore` | Fast, read-only recon: find files, entry points, data flow | read, bash, grep, find, ls | Fast/cheap model, falls back to your current model | Reports compressed findings, never edits |
| `Plan` | Turn Explore's findings (or your own) into a concrete implementation plan | read, bash, grep, find, ls | Inherits your current model | Never edits |
| `General` | Actual implementation: make the code changes an Explore/Plan investigation identified, or any task that needs real edits | read, bash, edit, write, grep, find, ls | Inherits your current model | Same read-write capability as you have; makes real changes |

`Explore` and `Plan` are read-only. `General` has the same read-write capability you do —
reach for it when a change is mechanical/independent enough to delegate (especially
several at once via parallel mode) rather than doing every edit yourself in sequence.
For a small, one-off change, just make it directly instead of delegating.

Subagents cannot themselves call `subagent` — they are leaves, not orchestrators. Keep
all delegation decisions in your own (parent) session.

For larger fan-out orchestration — many agents, loops over file lists, staged
map/verify/synthesize flows — prefer the `workflow` tool (if available), which runs a
JavaScript script coordinating these same read-only agents and returns one synthesized
result. `subagent` is for one-off or small parallel delegations.

A project can add its own agents (including ones that write) as `.pi/agents/<name>.md`
files — same frontmatter convention as the bundled agents above. See `agentScope` below.

## The `context` field — always fill it in

A subagent gets **only** its `task` string, plus a small automatic digest of your last
few conversation turns (as a fallback, not a substitute). It does not see the files
you've already read, tool results you've already seen, or decisions you've already made
unless you put them in `context`.

**Always pass `context`** with whatever the subagent actually needs:
- File paths and line numbers you already found.
- Decisions already made ("use approach B, not A, because...").
- Constraints ("don't touch files under vendor/").

A subagent given a bare one-line `task` and no `context` will waste its own turns
re-discovering things you already know.

## Modes

- **single** — one agent, one task. Default choice.
- **parallel** — `tasks: [...]`, up to 8 tasks / 4 concurrent. Use for independent work
  that can run at once, e.g. `Explore`ing two unrelated parts of a codebase together.

There is no chain mode. For a fixed pipeline (e.g. explore then plan), just call
`subagent` twice in sequence yourself and pass the first call's output back in as the
second call's `context` — you are already the orchestrator holding both results.

## Recommended pattern

```
clarify -> Explore -> Plan -> implement it yourself -> confirm before any risky follow-up
```

This is guidance, not a rigid workflow — decide per task whether you need both steps. For
a small, well-understood change, skip straight to implementing it yourself.

## Returning outcomes to the user

A subagent is a means to answer the user's request, not a background task whose
result can be silently acknowledged. After a subagent finishes, read its result
and give the user the relevant substantive outcome in the parent response.

- For an open-ended request such as "explore the repo", the findings are the
  answer: summarize the architecture, notable files, and any recommended next
  steps without waiting for the user to ask "what did it return?"
- For implementation, investigation, or review tasks, state what changed or
  was found, name relevant file paths, and include limitations, failures, or
  follow-ups that matter.
- Keep the relay proportional. Do not paste a huge transcript when a concise
  summary answers the request, but do not replace findings with empty praise
  such as "that helped" or "I can drill in further."
- If the result is incomplete, failed, or ambiguous, say so plainly and explain
  the next action rather than presenting it as success.

The tool result remains available in the conversation for detailed follow-up,
but the parent agent owns communicating its useful conclusion to the user.

## Observability

Every run writes `status.json`, `events.jsonl`, and a full `transcript.md` to
`~/.pi/agent/subagent-runs/<runId>/` for later inspection.
