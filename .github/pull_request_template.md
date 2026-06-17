<!-- Authoring rules (agents: read).
     Title: <type>(<scope>): <description> — type=feat|fix|chore, scope required, lowercase, no period, <72 chars.
       ✅ feat(insights): add retention graph export
       ❌ feat: Added retention export.   (capitalized, period, no scope)
     Description: high-level rationale, not a step-by-step replay. See "Rules for agent-authored PRs" lower down.
     Public OSS repo: no internal customers, incidents, or operational metrics.
-->

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
<!-- Agents: do NOT claim manual testing you haven't done. State that you're an agent and list only the automated tests you actually ran. -->

👉 _Stay up-to-date with [PostHog coding conventions](https://posthog.com/docs/contribute/coding-conventions) for a smoother review._

## Automatic notifications

- [ ] Publish to changelog?
- [ ] Alert Sales and Marketing teams?

## Docs update

<!-- Add the `skip-inkeep-docs` label if this PR should not trigger an automatic docs update from the Inkeep agent. -->

## 🤖 Agent context

<!-- Fill this section if an agent co-authored or authored this PR. Just don't duplicate info already present in preceding sections. Remove it for fully human-authored PRs. -->

<!-- Autonomy — keep one of the two options on the line below:
     - "Human-driven (agent-assisted)" when a person directed the work — assign that person as the PR assignee (the DRI).
     - "Fully autonomous" when no human drove it; leave the PR unassigned for the owning team to triage. -->

**Autonomy:** Human-driven (agent-assisted) - or - Fully autonomous

<!-- Keep this short: 1-3 short paragraphs or a handful of bullets — not an exhaustive log. Include:
     - tools/agent used and link to session. List the agent and tool names used, but do not include tool call results.
     - decisions made along the way (what was tried, rejected, chosen, and why)
     - anything else that helps reviewers
     Write reviewer-facing prose. Do not paste user prompts verbatim — paraphrase the intent in your own words.
     DO NOT INCLUDE sensitive data that may have been shared in an agent session.
-->
<!-- Rules for agent-authored PRs:
     - When a human directed the work, the PR must be attributable to that person, even if agent-assisted.
     - If a human directed this work, assign them as the PR assignee (the DRI) — actually set the assignee, don't just name them here. Leave a PR unassigned only when it is fully autonomous with no human driver (set Autonomy to "Fully autonomous").
     - Do not add a human Co-authored-by just for the sake of attribution — if no human was involved in the changes, own it as agent-authored.
     - Agent-authored PRs always require human review — do not self-merge or auto-approve.
     - Do NOT claim manual testing you haven't done.
     - GitHub PR descriptions render markdown, not fixed-width text. Do not hard-wrap prose at a column width or use space-aligned tables — use real markdown tables, headings, and fenced code blocks, and let GitHub flow the text.
     - Write with a crisp, direct Silicon Valley communication style. Use concise language that gets straight to the point. Prioritize clarity and brevity over elaborate explanations. Avoid corporate jargon, buzzwords, and unnecessary embellishments. Communicate as if you're explaining a complex concept to a smart colleague over coffee, keeping the tone light but substantive. Always stay professional.
     - For titles, headings, or bolded parts use "Sentence case" rather than "Title Case" (i.e. only capitalize the first word of the title/heading/bold text).
-->
