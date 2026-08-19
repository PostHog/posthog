<!-- This has to stand on its own: a reader who opens no files should still know why the PR is necessary and what it does. Length tracks the change, so a small diff gets a few bullets rather than a full-length body, and a section you have nothing for gets one line or "None". -->

## Problem

<!-- Who are we building for, what are their needs, why is this important? -->
<!-- First line: what is different for a person, and who they are. A fix says what breaks; a feature says what someone can now do; a chore says who is blocked. The code path goes underneath. -->

<!-- Does this fix an issue? Uncomment the line below with the issue ID to automatically close it when merged -->
<!-- Closes #ISSUE_ID -->

## Changes

<!-- For each change a person can notice, say what they will now see or do differently, not only the code path that does it. Mark the rest as mechanical so a reviewer knows nothing user-visible is hiding in it. -->

<!-- If there are frontend changes, please include screenshots. -->
<!-- PostHog employees: `hogli pr:upload-image <file>` uploads to the public PostHog/pr-assets repo and prints markdown to paste here. Never upload customer data, secrets, or internal info. -->

<!-- If a reference design was involved, include a link to the relevant Figma frame! -->

## How did you test this code?

<!-- Describe steps to reproduce and verify the changes, and what the expected behavior is. -->
<!-- Include automated tests if possible, otherwise describe the manual testing routine. -->
<!-- Agents: do NOT claim manual testing you haven't done. State what the agent wasn't able to do and list only the automated tests you (the agent) actually ran. -->
<!-- Added or changed tests? Name the regression each group catches that no existing test did — if you can't name it, it probably shouldn't be in this PR. https://posthog.com/handbook/engineering/conventions/backend-coding#testing -->
<!-- Don't recite pass counts for suites CI runs; the checks report those with more authority. Link the evidence instead (run, permalink, error tracking issue), and say what you did not check. Long transcripts go in a <details> block. -->

👉 _Stay up-to-date with [PostHog coding conventions](https://posthog.com/docs/contribute/coding-conventions) for a smoother review._

## Automatic notifications

- [ ] Publish to changelog?

## Docs update

<!-- Add the `skip-inkeep-docs` label if this PR should not trigger an automatic docs update from the Inkeep agent. -->

## 🤖 Agent context

<!-- Fill this section if an agent co-authored or authored this PR. Remove it for fully human-authored PRs. -->

<!-- Autonomy — keep one of the two options on the line below:
     - "Human-driven (agent-assisted)" when a person directed the work — assign that person as the PR assignee (the DRI).
     - "Fully autonomous" when no human drove it; leave the PR unassigned for the owning team to triage. -->

**Autonomy:** Human-driven (agent-assisted) - or - Fully autonomous

<!-- Definition of done (agents): not done until each gate below holds. Verify against the named artifact or skill — don't assume. Add gates as the PR touches more areas.
     - Patch coverage: the lines this PR changed are covered, or the uncovered ones are justified under "How did you test this code?". Don't pad untouched code to lift the number. Check the "🧪 Backend test coverage" PR comment (and its patch-coverage artifact).
     - Public artifact: nothing in this PR — code, fixtures and sample data, comments, commit messages, or this description — carries material from the agent session that isn't already public. If the work drew on a customer conversation, ticket, or log, say so here and state that the committed data is invented. Renaming people, hosts, and identifiers does not clear real material; see AGENTS.md "Public open source repo guidance".
-->

<!-- Keep this short: 1-3 short paragraphs or a handful of bullets — not an exhaustive log. Include:
     - tools/agent used and link to session. List the agent and tool names used, but do not include tool call results.
     - skills invoked: always explicitly call out any repo-provided or public skills (e.g. /django-migrations, /improving-drf-endpoints) that were invoked while producing this PR. This helps reviewers judge where and how the code was shaped by an agent.
     - decisions made along the way: what changed across the session. The reason the shipped design beats the obvious alternative goes in Changes instead, where a reviewer will actually see it.
     - anything else that helps reviewers
     Write reviewer-facing prose. Do not paste user prompts verbatim — paraphrase the intent in your own words.
     This is the ONLY section that should contain descriptions of what this PR might have looked like before its present final state.
     Don't duplicate info already present in preceding sections.
     DO NOT INCLUDE sensitive data that may have been shared in an agent session — that applies to every part of this PR, not just this section.
-->

<!-- Overall PR authoring rules for agents:
- Title: <type>(<scope>): <description> — type=feat|fix|chore, scope required, lowercase, no period, <72 chars.
  ✅ feat(insights): add retention graph export
  ❌ feat: Added retention export.   (capitalized, period, no scope)
- Description: high-level rationale, not a step-by-step replay.
- Voice: the subject of every sentence is the change, never its author. No "I", "me" or "my" anywhere in the body. "I (actually Claude)" is worse than either half: it hands the assignee an account of work they did not do. Authorship is one stated fact in the Agent context section below.
- Body: pass it straight to the creation tool's `body` arg (GitHub MCP `create_pull_request` body, or `gh pr create --body-file -` via stdin) — don't write it to a temp file first; the arg preserves markdown and newlines verbatim.
- Flow and topology changes: include separate before-and-after Mermaid `flowchart` blocks with PostHog colors. This includes CI wiring, pipelines, state machines, and request paths. Use `/writing-pr-descriptions` for the palette and role mapping.
- Public OSS repo: no internal customers, incidents, or operational metrics.
- Stack instead of stuffing: if the diff holds two or more separable steps (migration then behavior, rename then rewrite), open a stack rather than one big PR. See AGENTS.md, "Stacked PRs" and /stacking-prs.
- Simplify before opening: if your agent has a behavior-preserving cleanup pass (Claude Code: `/simplify`), run it on a non-trivial diff before final tests and preflight, since it edits the tree. Skip it for small mechanical changes.
- Draft by default: open new PRs as drafts (`gh pr create --draft`) — drafts run only a narrow CI subset and save runner credits. Fix CI and run affected tests locally before marking ready for review.
- Labels: apply `skip-agent-review` for trivial/chore PRs that don't need Copilot or Greptile review.
- When a human directed the work, the PR must be attributable to that person, even if agent-assisted.
- If a human directed this work, assign them as the PR assignee (the DRI) — actually set the assignee, don't just name them here. Leave a PR unassigned only when it is fully autonomous with no human driver (set Autonomy to "Fully autonomous").
- Never write a GitHub @mention or username you have not verified this session. Resolve a real handle from `gh api user` (current user) or the PR's actual author/assignee via `gh pr view --json author,assignees` — never infer a handle from a display name.
- Do not add a human Co-authored-by just for the sake of attribution — if no human was involved in the changes, own it as agent-authored.
- Agent-authored PRs always require human review — do not self-merge or auto-approve.
- Do NOT claim manual testing you haven't done.
- Shape and style: invoke the `/writing-pr-descriptions` skill before writing this body. In short: lead with the effect a person sees rather than the code path behind it, make the body stand alone for a reader who opens no files, size it to the change, link evidence rather than asserting what CI already reports, then hold what's left to one fact per bullet in under 25 words. A body that got longer as bullets was not cut.
-->
