---
name: qa-team
description: >
  Multi-agent QA review team for code changes. This skill should be used when the user
  asks to "review my code", "run QA", "qa-team", "review this branch", "code review",
  "check my changes", or wants a comprehensive multi-perspective code review of the
  current branch's changes. Spawns parallel specialist agents (security, database,
  reliability, compatibility, data integrity, performance, frontend, copy) that
  independently review the diff and produce a converged report. Also includes
  two generalist reviewers for convergence validation.
---

# QA Team: Multi-Agent Code Review

A team of specialist agents independently review the current branch's changes against
real incident patterns. Their findings are synthesized into a single report with
convergence analysis.

**Agent independence is critical.** Each agent receives only its own persona definition,
the relevant incident patterns for its focus area, and the diff. Agents must NOT be told
about other agents, their codenames, how many agents are running, or that a convergence
analysis will be performed. This ensures findings are fully independent.

## Workflow

### Step 1: Gather the diff

Determine the base branch. If the user provided `$ARGUMENTS`, use that as the base branch.
Otherwise, default to `master`.

Run these commands to collect context:

```bash
git diff <base>...HEAD --name-only
git diff <base>...HEAD
git log <base>...HEAD --oneline
```

Store the full diff, changed file list, and commit messages. These will be passed to each agent.

If there are no changes, inform the user and stop.

### Step 2: Classify changed files

Categorize changed files to determine which agents are relevant:

| File pattern                                          | Relevant agents                                    |
| ----------------------------------------------------- | -------------------------------------------------- |
| `*.py` (migrations)                                   | database, reliability, compatibility               |
| `*.py` (Django views/API)                             | security, reliability, performance, data-integrity |
| `*.py` (Celery tasks)                                 | reliability, performance, data-integrity           |
| `*.rs` (Rust services)                                | security, performance, compatibility, reliability  |
| `*.tsx`, `*.ts` (frontend)                            | frontend, security, performance, copy              |
| `*.sql`, ClickHouse queries                           | database, performance, data-integrity              |
| Helm charts, ArgoCD, k8s                              | compatibility, reliability                         |
| `requirements*.txt`, `pyproject.toml`, `package.json` | security, compatibility                            |
| SDK/extension code                                    | compatibility, frontend, security, copy            |
| Any file with user-facing strings                     | copy                                               |
| GitHub Actions workflows                              | security                                           |

Always run at least 4 specialist agents. If fewer than 4 are relevant based on file
classification, add the most broadly applicable ones (reliability, security, performance,
compatibility) until at least 4 specialists are active.

**Always launch both generalist agents** (`generalist-a` and `generalist-b`) regardless of
file classification. They review all changes.

### Step 3: Launch parallel review agents

Launch all relevant agents **simultaneously** using the Agent tool.

**CRITICAL:** Launch ALL agents in a single message with multiple Agent tool calls so they
run in true parallel. Do NOT launch them sequentially.

**CRITICAL — Agent independence:** Each agent must operate in total isolation. Do NOT
include any of the following in any agent's prompt:

- Names, codenames, or descriptions of other agents
- The number of agents being launched
- That a convergence analysis will be performed
- That other reviewers are looking at the same code
- Any reference to a "team" of reviewers

Each agent believes it is the sole reviewer. This ensures fully independent findings.

#### Specialist agent prompt template

For each specialist agent (security, database, reliability, performance, frontend,
compatibility, data-integrity, copy), build the prompt from these parts:

1. **Role** — Only this agent's persona description and checklist from `references/personas.md`
2. **Context** — Only the incident patterns relevant to this agent's focus from
   `references/incident-patterns.md`. Omit for the copy agent.
3. **Diff material** — Changed files, commit messages, and the full diff

```text
You are a code reviewer specializing in {FOCUS_AREA}.

## Your expertise
{PERSONA_DESCRIPTION_AND_CHECKLIST from references/personas.md — this agent's section only}

## Known failure patterns
{RELEVANT_PATTERNS from references/incident-patterns.md — only patterns matching
this agent's focus area. Omit this entire section for the copy agent.}

## Code changes to review

### Changed files
{FILE_LIST}

### Commit messages
{COMMIT_LOG}

### Full diff
{FULL_DIFF}

## Instructions

1. Read the full diff carefully. For each changed file, also read the surrounding code
   context using the Read tool (at least 50 lines above and below each change) to
   understand what the change does in context.

2. Apply your review checklist systematically. For each item, determine if the change
   introduces a risk.

3. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** `file:line` — Description of the issue
  - Why it matters: {explanation referencing known failure patterns if applicable}
  - Suggestion: {specific fix or mitigation}

If no findings: "No issues found in my focus area."

**Checklist Coverage:**
List each checklist item and mark it [x] reviewed or [-] not applicable.

**Summary:**
One paragraph summarizing your overall assessment.
```

#### Generalist agent prompt template

Always launch both generalist agents (`generalist-a` and `generalist-b`). Their prompts
are intentionally different — each has a distinct review angle to maximize the chance
of surfacing issues that specialists miss.

**Generalist A** — reviews from a "new team member" perspective:

```text
You are a senior software engineer reviewing this code change for the first time.
You have no prior context about the codebase — approach it with fresh eyes.

Focus on things that would concern you if you saw this code in a pull request:
- Does the code do what the commit messages claim?
- Are there obvious bugs, logic errors, or edge cases?
- Is error handling adequate? What happens when things fail?
- Are there race conditions or concurrency issues?
- Is the code readable and maintainable?
- Are there any "that looks wrong" moments?

Do NOT focus on style, formatting, or minor nits. Focus on correctness and safety.

## Code changes to review

### Changed files
{FILE_LIST}

### Commit messages
{COMMIT_LOG}

### Full diff
{FULL_DIFF}

## Instructions

1. Read the full diff carefully. For each changed file, also read the surrounding code
   context using the Read tool (at least 50 lines above and below each change).

2. Think about what could go wrong. Consider edge cases, failure modes, and
   assumptions the author may have made.

3. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** `file:line` — Description of the issue
  - Why it matters: {explanation}
  - Suggestion: {specific fix or mitigation}

If no findings: "No issues found."

**Summary:**
One paragraph summarizing your overall assessment.
```

**Generalist B** — reviews from an "adversarial tester" perspective:

```text
You are a QA engineer who tries to break things. Your job is to think about how
this code could fail in production, be misused, or cause unexpected behavior.

Think like an attacker, an impatient user, a misconfigured deployment, or an
edge-case dataset. For each change, ask:
- What if the input is malformed, huge, empty, or malicious?
- What if the external service is slow, down, or returns garbage?
- What if two requests hit this code at the same time?
- What if this runs against a database with millions of rows?
- What happens during deployment — is there a window where old and new code coexist?
- What if a developer misunderstands this code and extends it incorrectly?

Do NOT focus on style or readability. Focus on breakability.

## Code changes to review

### Changed files
{FILE_LIST}

### Commit messages
{COMMIT_LOG}

### Full diff
{FULL_DIFF}

## Instructions

1. Read the full diff carefully. For each changed file, also read the surrounding code
   context using the Read tool (at least 50 lines above and below each change).

2. Try to find ways to break it. Think adversarially.

3. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** `file:line` — Description of the issue
  - Why it matters: {explanation}
  - Suggestion: {specific fix or mitigation}

If no findings: "No issues found."

**Summary:**
One paragraph summarizing your overall assessment.
```

### Step 4: Synthesize the report

After all agents complete, compile their findings into a unified report.

#### 4a. Convergence analysis

Check if multiple agents flagged the same file or concern. Convergent findings
(independently identified by 2+ agents) are higher confidence and should be highlighted
in the summary.

#### 4b. Risk scoring

Compute an overall risk score:

- CRITICAL: Any agent returned Risk Level CRITICAL -> overall CRITICAL
- HIGH: 2+ agents returned Risk Level HIGH, or 1 HIGH + 2 MEDIUM agents -> overall HIGH
- MEDIUM: 1 agent returned Risk Level HIGH, or 3+ agents returned Risk Level MEDIUM -> overall MEDIUM
- LOW: Only LOW/NONE agent risk levels -> overall LOW

#### 4c. Verdict

Map overall risk to a verdict:

- ✅ **APPROVE** — Overall LOW risk, no actionable findings
- 💬 **APPROVE WITH NITS** — MEDIUM risk, minor suggestions that won't block merge
- ⚠️ **REQUEST CHANGES** — HIGH risk, specific fixes needed before merge
- 🚫 **BLOCKED** — CRITICAL risk, blocking security/data issues found

#### 4d. Final report format

Write the report to `QAREPORT.md` in the repository root using the Write tool,
then present a brief summary to the user with the verdict and top findings.

The report MUST use emojis for visual structure and avoid long prose paragraphs.
Keep everything scannable — tables, checklists, and short bullet points.

```markdown
# 🔍 QA Team Review Report

| Key                 | Value                   |
| ------------------- | ----------------------- |
| **Branch**          | `{branch_name}`         |
| **Base**            | `{base_branch}`         |
| **Files changed**   | {count}                 |
| **Agents deployed** | {emoji + codename list} |
| **Date**            | {YYYY-MM-DD}            |

---

## 📋 Summary

{2-4 bullet points: what was changed and why. No long paragraphs.}

### Key findings

- {1-line per convergent or critical/high finding, with emoji severity prefix}

---

## 🏁 Verdict

> {emoji} **{APPROVE / APPROVE WITH NITS / REQUEST CHANGES / BLOCKED}**

{1-2 sentences explaining the verdict. Reference the top blocking items if not approving.}

---

## 👥 Agent summaries

| Agent             | Risk                 | Summary                           |
| ----------------- | -------------------- | --------------------------------- |
| 🔒 security       | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🗄️ database       | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🔄 reliability    | {risk emoji + level} | {1-2 sentence summary from agent} |
| ⚡ performance    | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🎨 frontend       | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🔗 compatibility  | {risk emoji + level} | {1-2 sentence summary from agent} |
| 📊 data-integrity | {risk emoji + level} | {1-2 sentence summary from agent} |
| ✏️ copy           | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🧑‍💻 generalist-a   | {risk emoji + level} | {1-2 sentence summary from agent} |
| 🕵️ generalist-b   | {risk emoji + level} | {1-2 sentence summary from agent} |

(Only include rows for agents that were deployed.)

**Note:** ✏️ copy findings are always non-blocking nits. 🧑‍💻 generalist-a and 🕵️ generalist-b
are independent generalist reviewers used for convergence validation — their findings
carry extra weight when they independently match a specialist's finding.

Risk emojis: 🔴 CRITICAL, 🟠 HIGH, 🟡 MEDIUM, 🟢 LOW, ⚪ NONE

---

## 📝 Findings

Actionable findings as a checklist table, sorted by priority (highest first).

Each row is a checklist item. The `Status` column starts as `⬜ Open`.
Use convergence markers when 2+ agents flagged the same issue.

| #   | Status  | Priority    | Finding       | Location    | Agents      | Reasoning                                                    | Suggested fix  |
| --- | ------- | ----------- | ------------- | ----------- | ----------- | ------------------------------------------------------------ | -------------- |
| 1   | ⬜ Open | 🔴 Critical | {short title} | `file:line` | {codenames} | {why it matters — reference incident patterns if applicable} | {specific fix} |
| 2   | ⬜ Open | 🟠 High     | {short title} | `file:line` | {codenames} | {reasoning}                                                  | {fix}          |
| 3   | ⬜ Open | 🟡 Medium   | {short title} | `file:line` | {codenames} | {reasoning}                                                  | {fix}          |
| ... | ...     | ...         | ...           | ...         | ...         | ...                                                          | ...            |
| N   | ⬜ Open | 🟢 Low      | {short title} | `file:line` | {codenames} | {reasoning}                                                  | {fix}          |

Priority mapping:

- 🔴 Critical — Security vulnerability, data loss, or production outage risk
- 🟠 High — Significant bug or security concern, must fix before merge
- 🟡 Medium — Should fix, but not a merge blocker
- 🟢 Low — Nit or minor improvement, nice to have

Convergent findings (flagged by 2+ agents independently) should be noted
in the `Agents` column and carry higher confidence.
```

## Reference Files

### Persona Definitions

- **`references/personas.md`** -- Full persona descriptions, context, and review checklists for specialist agents (not used for generalists — they have their own prompts)

### Incident Patterns

- **`references/incident-patterns.md`** -- Synthesized failure patterns from production incidents, used to ground specialist agent reviews in real-world failure modes (not used for generalists)
