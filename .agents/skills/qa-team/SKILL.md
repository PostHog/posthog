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

Create a run directory **outside the repository** (session scratchpad or `mktemp -d` — never
inside the repo), then collect context into it:

```bash
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qa-team-XXXXXX")"
mkdir -p "$RUN_DIR/personas" "$RUN_DIR/claimed"
git diff <base>...HEAD --name-only > "$RUN_DIR/files.txt"
git log <base>...HEAD --oneline > "$RUN_DIR/commits.txt"
git diff <base>...HEAD > "$RUN_DIR/diff.patch"
```

Review agents read the diff from these files by absolute path — do NOT paste the diff into
agent prompts (see the launch protocol in Step 3 for why).

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

### Step 3: Launch the review agents (cache-aware protocol)

**Why this protocol exists:** every agent request carries a large fixed prefix (system
prompt, tools, project context, and the user prompt) that is prompt-cached **only when the
prompt is byte-identical across agents**. Prompt caching is strict-prefix based: one
divergent character anywhere in the prompt forces the entire prefix — tens of thousands of
tokens — to be re-ingested at full price by every agent. Three rules follow:

1. **Every agent gets the same prompt, byte for byte.** Build the prompt string once and
   reuse it exactly. Do not customize, reorder, or re-type any part of it per agent.
2. **Per-agent divergence (the persona) arrives via a tool result, not the prompt.** Each
   agent's first action is to run a claim script that atomically assigns it a persona.
   Tool results come after the shared prefix, so they don't break the cache. Never deliver
   the persona as a follow-up message to a completed agent — resuming a finished agent
   rebuilds its request from scratch and misses the cache entirely.
3. **Stagger the launch.** Run the first agent alone until it claims its persona (the
   claim is the signal that its first request finished and the shared prefix is cached),
   then launch all remaining agents in parallel. A simultaneous cold launch makes every
   agent write the prefix instead of reading it.

**CRITICAL — Agent independence:** Each agent must operate in total isolation. Do NOT
include any of the following in the shared prompt or in any persona file:

- Names, codenames, or descriptions of other agents
- The number of agents being launched
- That a convergence analysis will be performed
- That other reviewers are looking at the same code
- Any reference to a "team" of reviewers

Each agent believes it is the sole reviewer. This ensures fully independent findings.
(The persona queue on disk necessarily contains the other personas; the shared prompt
forbids agents from inspecting the run directory, which preserves independence in
practice.)

#### 3a. Write the persona files

Write one file per selected agent to `$RUN_DIR/personas/`, named with a numeric prefix so
claim order is deterministic (`01-security.md`, `02-database.md`, ..., `09-generalist-a.md`,
`10-generalist-b.md`). The number of persona files must equal the number of agents you
will launch.

For each **specialist** (security, database, reliability, performance, frontend,
compatibility, data-integrity, copy), the file contains:

```text
Your assigned review focus: {FOCUS_AREA}

## Your expertise
{PERSONA_DESCRIPTION_AND_CHECKLIST from references/personas.md — this agent's section only}

## Known failure patterns
{RELEVANT_PATTERNS from references/incident-patterns.md — only patterns matching
this agent's focus area. Omit this entire section for the copy persona.}
```

Always include both **generalist** personas. Generalist A (fresh-eyes senior engineer):

```text
Your assigned review focus: general correctness and safety

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
This focus has no formal checklist — omit the Checklist Coverage section from your review.
```

Generalist B (adversarial tester):

```text
Your assigned review focus: breakability

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
This focus has no formal checklist — omit the Checklist Coverage section from your review.
```

#### 3b. Write the claim script

```bash
cat > "$RUN_DIR/claim.sh" <<'EOF'
#!/bin/bash
dir="$(cd "$(dirname "$0")" && pwd)"
for f in "$dir"/personas/*.md; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  if mv "$f" "$dir/claimed/$name" 2>/dev/null; then
    cat "$dir/claimed/$name"
    exit 0
  fi
done
echo "ERROR: no persona available" >&2
exit 1
EOF
chmod +x "$RUN_DIR/claim.sh"
```

`mv` is atomic, so concurrent agents each claim a distinct persona.

#### 3c. Build the ONE shared prompt

Substitute the absolute `$RUN_DIR` path once, then reuse the resulting string verbatim for
every agent:

```text
You are a code reviewer. Your specific review focus is pre-assigned. Follow these steps
exactly:

1. FIRST action — run this exact command with the Bash tool to receive your review focus:

   bash {RUN_DIR}/claim.sh

   It prints your assigned focus, expertise, checklist, and known failure patterns.
   Conduct your entire review through that lens. Do not read, list, or otherwise inspect
   anything inside {RUN_DIR} other than running this command and reading the three files
   listed below.

2. Read the code changes to review:
   - {RUN_DIR}/files.txt — changed files
   - {RUN_DIR}/commits.txt — commit messages
   - {RUN_DIR}/diff.patch — the full diff

3. Read the full diff carefully. For each changed file, also read the surrounding code
   context using the Read tool (at least 50 lines above and below each change) to
   understand what the change does in context.

4. Apply your assigned review checklist systematically. For each item, determine if the
   change introduces a risk.

5. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** `file:line` — Description of the issue
  - Why it matters: {explanation referencing known failure patterns if applicable}
  - Suggestion: {specific fix or mitigation}

If no findings: "No issues found in my focus area."

**Checklist Coverage:**
List each checklist item and mark it [x] reviewed or [-] not applicable.
(Omit this section if your assigned focus says it has no formal checklist.)

**Summary:**
One paragraph summarizing your overall assessment.
```

#### 3d. Launch order

1. Launch the **first agent** with the shared prompt (background is fine).
2. Wait until it has claimed its persona — poll for a file to appear in
   `$RUN_DIR/claimed/` (e.g. `timeout 90 bash -c 'until [ -n "$(ls -A '"$RUN_DIR"'/claimed)" ]; do sleep 1; done'`).
   If the poll times out, launch the rest anyway — a cache miss costs money, not
   correctness.
3. Launch **all remaining agents in a single message** with multiple Agent tool calls so
   they run in parallel — each with the byte-identical shared prompt.
4. Collect every agent's report as it completes.

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

- **`references/personas.md`** -- Full persona descriptions, context, and review checklists for specialist agents (not used for generalists — their persona files are defined inline in Step 3a)

### Incident Patterns

- **`references/incident-patterns.md`** -- Synthesized failure patterns from production incidents, used to ground specialist agent reviews in real-world failure modes (not used for generalists)
