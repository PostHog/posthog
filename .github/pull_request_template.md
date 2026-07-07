## Problem

<!-- Who are we building for, what are their needs, why is this important? -->

<!-- Does this fix an issue? Uncomment the line below with the issue ID to automatically close it when merged -->
<!-- Closes #ISSUE_ID -->

## Changes

<!-- If there are frontend changes, please include screenshots. -->
<!-- If a reference design was involved, include a link to the relevant Figma frame! -->

## How did you test this code?

<!-- Describe steps to reproduce and verify the changes, and what the expected behavior is. -->
<!-- Include automated tests if possible, otherwise describe the manual testing routine. -->
<!-- Agents: do NOT claim manual testing you haven't done. State what the agent wasn't able to do and list only the automated tests you (the agent) actually ran. -->
<!-- Added or changed tests? Name the regression each group catches that no existing test did — if you can't name it, it probably shouldn't be in this PR. https://posthog.com/handbook/engineering/conventions/backend-coding#testing -->

👉 _Stay up-to-date with [PostHog coding conventions](https://posthog.com/docs/contribute/coding-conventions) for a smoother review._

## Automatic notifications

- [ ] Publish to changelog?
- [ ] Alert Sales and Marketing teams?

## Docs update

<!-- Add the `skip-inkeep-docs` label if this PR should not trigger an automatic docs update from the Inkeep agent. -->

## 🤖 Agent context

<!-- Fill this section if an agent co-authored or authored this PR. Remove it for fully human-authored PRs. -->

<!-- Autonomy — keep one of the two options on the line below:
     - "Human-driven (agent-assisted)" when a person directed the work — assign that person as the PR assignee (the DRI).
     - "Fully autonomous" when no human drove it; leave the PR unassigned for the owning team to triage. -->

**Autonomy:** Human-driven (agent-assisted) - or - Fully autonomous

<!-- Keep this short: 1-3 short paragraphs or a handful of bullets — not an exhaustive log. Include:
     - tools/agent used and link to session. List the agent and tool names used, but do not include tool call results.
     - skills invoked: always explicitly call out any repo-provided or public skills (e.g. /django-migrations, /improving-drf-endpoints) that were invoked while producing this PR. This helps reviewers judge where and how the code was shaped by an agent.
     - decisions made along the way (what was tried, rejected, chosen, and why)
     - anything else that helps reviewers
     Write reviewer-facing prose. Do not paste user prompts verbatim — paraphrase the intent in your own words.
     This is the ONLY section that should contain descriptions of what this PR might have looked like before its present final state.
     Don't duplicate info already present in preceding sections.
     DO NOT INCLUDE sensitive data that may have been shared in an agent session.
-->

<!-- Overall PR authoring rules for agents:
- Title: <type>(<scope>): <description> — type=feat|fix|chore, scope required, lowercase, no period, <72 chars.
  ✅ feat(insights): add retention graph export
  ❌ feat: Added retention export.   (capitalized, period, no scope)
- Description: high-level rationale, not a step-by-step replay.
- Body: pass it straight to the creation tool's `body` arg (GitHub MCP `create_pull_request` body, or `gh pr create --body-file -` via stdin) — don't write it to a temp file first; the arg preserves markdown and newlines verbatim.
- Public OSS repo: no internal customers, incidents, or operational metrics.
- Draft by default: open new PRs as drafts (`gh pr create --draft`) — drafts run only a narrow CI subset and save runner credits. Fix CI and run affected tests locally before marking ready for review.
- Labels: apply `skip-agent-review` for trivial/chore PRs that don't need Copilot or Greptile review.
- When a human directed the work, the PR must be attributable to that person, even if agent-assisted.
- If a human directed this work, assign them as the PR assignee (the DRI) — actually set the assignee, don't just name them here. Leave a PR unassigned only when it is fully autonomous with no human driver (set Autonomy to "Fully autonomous").
- Never write a GitHub @mention or username you have not verified this session. Resolve a real handle from `gh api user` (current user) or the PR's actual author/assignee via `gh pr view --json author,assignees` — never infer a handle from a display name.
- Do not add a human Co-authored-by just for the sake of attribution — if no human was involved in the changes, own it as agent-authored.
- Agent-authored PRs always require human review — do not self-merge or auto-approve.
- Do NOT claim manual testing you haven't done.
- GitHub PR descriptions render markdown, not fixed-width text. Do not hard-wrap prose at a column width or use space-aligned tables — use real markdown tables, headings, and fenced code blocks, and let GitHub flow the text.
- Use GitHub's rich markdown when it makes review faster, never as decoration:
  - If the change alters a flow or topology (CI wiring, pipelines, state machines, request paths), include before/after mermaid diagrams as two separate `flowchart LR` blocks, before first. Keep them simple: a syntax error renders as an error block. Skip diagrams for trivial changes.
  - Use alerts (`> [!WARNING]`, `> [!NOTE]`) for behavior changes and risk callouts.
  - If you have to include long supporting content (test output, logs), collapse it in `<details>` blocks.
  - Use fenced `diff` code blocks for config before/after.
  - Line-range permalinks to code in this repo render as embedded snippets: prefer them over pasting existing code.
- Write with a crisp, direct Silicon Valley communication style. Use concise language that gets straight to the point. Sentences that are easy on the reader, paragraphs that are each about one thing. Prioritize clarity and brevity over elaborate explanations. Avoid corporate jargon, buzzwords, and unnecessary embellishments. Communicate as if you're explaining a complex concept to a smart colleague over coffee, keeping the tone light but substantive. No em-dashes, only en-dashes if needed. Spare use of inline code. Limited use of the colon and semicolon.
- Write from a first person perspective of the author of a human-driven PR. Although if something was done by an agent (i.e. you), make that clear with something like "I (or, actually Claude/Codex/etc.) did blah".
- For titles, headings, or bolded parts use "Sentence case" rather than "Title Case" (i.e. only capitalize the first word of the title/heading/bold text).
-->
