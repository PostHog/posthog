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

The run directory holds the persona queue and claim script (Step 3); the diff itself is
embedded into the shared agent prompt by the workflow script, composed once (see Step 3
for why). Keep `diff.patch` on disk anyway — it is the fallback path.

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
tokens — to be re-ingested at full price by every agent. Four rules follow:

1. **Every agent gets the same prompt, byte for byte — including the full diff.** The
   diff inside the identical prompt is part of the shared cached prefix, so followers
   ingest it at cache-read prices instead of each re-paying write prices for a
   file-read tool result.
2. **The prompt is composed once, by a Workflow script, not re-typed per agent.** The
   orchestrator emits the diff a single time (into the workflow `args`); the script
   string-builds the identical prompt for every agent. Hand-typing the diff into N
   Agent-tool prompts pays N× output-token prices and risks a stray byte difference
   silently killing the cache.
3. **Per-agent divergence (the persona) arrives via a tool result, not the prompt.** Each
   agent's first action is to run a claim script that atomically assigns it a persona.
   Tool results come after the shared prefix, so they don't break the cache. Never deliver
   the persona as a follow-up message to a completed agent — resuming a finished agent
   rebuilds its request from scratch and misses the cache entirely.
4. **Stagger the launch.** A dedicated warm-up agent (first persona in the queue: reply
   OK and stop) runs to completion first, writing the shared prefix to cache in one cheap
   turn; then all reviewers launch in parallel and read it. A simultaneous cold launch
   makes every agent write the prefix instead of reading it.

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
claim order is deterministic (`00-warmup.md`, `01-security.md`, `02-database.md`, ...,
`09-generalist-a.md`, `10-generalist-b.md`). The number of persona files must equal the
number of agents you will launch (reviewers + the warm-up agent).

Always write `00-warmup.md` first — it is claimed by the cache warm-up agent:

```text
Your assigned review focus: none (calibration slot)

This run slot is a calibration pass only. Do NOT review the code, do NOT use any further
tools, and do NOT produce the review format. Reply with exactly: OK
```

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

#### 3c. The ONE shared prompt

The prompt is assembled by the workflow script in 3d — `{RUN_DIR}`, `{FILE_LIST}`,
`{COMMIT_LOG}`, and `{FULL_DIFF}` are filled in from `args`, identically for every agent:

```text
You are a code reviewer. Your specific review focus is pre-assigned. Follow these steps
exactly:

1. FIRST action — run this exact command with the Bash tool to receive your review focus:

   bash {RUN_DIR}/claim.sh

   It prints your assigned focus, expertise, checklist, and known failure patterns.
   Conduct your entire review through that lens, and follow any stop instruction it
   contains. Do not read, list, or otherwise inspect anything inside {RUN_DIR} other
   than running this command.

2. The code changes to review:

   ### Changed files
   {FILE_LIST}

   ### Commit messages
   {COMMIT_LOG}

   ### Full diff
   {FULL_DIFF}

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

#### 3d. Launch via the Workflow tool

Invoke the Workflow tool with the script below, passing the diff material through `args`
(actual JSON values, emitted once):

```js
export const meta = {
  name: 'qa-team-review',
  description: 'Launch QA review agents with a shared cached prompt prefix',
  phases: [{ title: 'Warm cache' }, { title: 'Review' }],
}
// args: { runDir, fileList, commitLog, diff, reviewerCount }
const PROMPT = `You are a code reviewer. Your specific review focus is pre-assigned. Follow these steps exactly:
...the full shared prompt from 3c, with ${args.runDir}, ${args.fileList},
${args.commitLog}, ${args.diff} interpolated...`

phase('Warm cache')
// Claims 00-warmup.md, replies OK, and — critically — writes the shared prompt
// prefix (diff included) to the prompt cache in one cheap turn.
await agent(PROMPT, { label: 'warmup', phase: 'Warm cache' })

phase('Review')
const reviews = await parallel(
  Array.from(
    { length: args.reviewerCount },
    (_, i) => () => agent(PROMPT, { label: `reviewer-${i + 1}`, phase: 'Review' })
  )
)
return reviews.filter(Boolean)
```

`reviewerCount` must equal the number of persona files minus the warm-up. Every `agent()`
call uses the same `PROMPT` constant — never build per-agent variants. The workflow's
return value is the list of reviews for Step 4.

**Fallbacks:**

- If the Workflow tool is unavailable, launch agents directly with the Agent tool: build
  one shared prompt that references the run-dir files instead of embedding the diff
  (`Read {RUN_DIR}/diff.patch` etc. — hand-typing the diff N times costs more than the
  cache saves), launch the first agent, poll `$RUN_DIR/claimed/` until its claim appears
  (`timeout 90 bash -c 'until [ -n "$(ls -A '"$RUN_DIR"'/claimed)" ]; do sleep 1; done'`),
  then launch the rest in a single message in parallel. If the poll times out, launch
  anyway — a cache miss costs money, not correctness.
- For very large diffs (roughly >200 KB), don't embed the diff in the prompt — use the
  same file-reference prompt as above inside the workflow script, keeping everything else
  identical.

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
