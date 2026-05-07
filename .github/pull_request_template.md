<!-- PR authoring rules — read before filling the sections below.

     PR title (conventional commits): <type>(<scope>): <description>
       Both type and scope are required. Agents commonly skip them — do not.
       Type: feat | fix | chore (chore covers docs, tests, config, CI, refactors).
       Scope: the area touched (e.g. insights, cohorts, devex, ci, llma for LLM analytics).
       Description: lowercase, no trailing period, under 72 chars, imperative mood.
       ✅ feat(insights): add retention graph export
       ✅ chore(ci): bump node to 24
       ❌ Add retention export                — missing type and scope
       ❌ feat: Add retention export.         — capitalized, trailing period, no scope

     PR description: keep sections high-level. Focus on rationale and architecture
     for the human reviewer, not a step-by-step replay of implementation work.

     Public OSS repo: title and description must be safe for external readers.
     No internal customer names, private incidents, private Slack threads, or
     operational metrics (e.g. exact row counts, affected team counts).
       ❌ fix: patches issue from acme-co prod
       ❌ fix: works fine on our 12M-row table
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

## Publish to changelog?

<!-- For features only -->

<!-- If publishing, you must provide changelog details in the #changelog Slack channel. You will receive a follow-up PR comment or notification. -->

<!-- If not, write "no" or "do not publish to changelog" to explicitly opt-out of posting to #changelog. Removing this entire section will not prevent posting. -->

## Docs update

<!-- Add the `skip-inkeep-docs` label if this PR should not trigger an automatic docs update from the Inkeep agent. -->

## 🤖 Agent context

<!-- Fill this section if an agent co-authored or authored this PR. Remove it for fully human-authored PRs. -->
<!-- Include:
     - tools/agent used and link to session
     - decisions made along the way (what was tried, rejected, chosen, and why)
     - anything else that helps reviewers
     Write reviewer-facing prose. Do not paste user prompts verbatim — paraphrase the intent in your own words.
-->
<!-- Rules for agent-authored PRs:
     - All PRs must be attributable to a human author, even if agent-assisted.
     - Do not add a human Co-authored-by just for the sake of attribution — if no human was involved in the changes, own it as agent-authored.
     - Agent-authored PRs always require human review — do not self-merge or auto-approve.
     - Do NOT claim manual testing you haven't done.
-->
