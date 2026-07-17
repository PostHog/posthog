#!/usr/bin/env node
// Build the qa-team Workflow launch scripts for a review run.
//
// Usage: node build_launch_scripts.js <RUN_DIR>
//
// Reads diff.patch, files.txt, commits.txt, and personas/ from RUN_DIR and writes
// launch_first.js and launch_rest.js next to them, with the shared review prompt
// JSON-encoded into both. Building the scripts with this tool (instead of having
// the orchestrating agent type them) keeps the two prompts byte-identical — the
// prompt-cache invariant the launch protocol depends on — and means the diff never
// passes through the model as output tokens.

const fs = require('fs')
const path = require('path')

// Above this size the diff is not inlined into the prompt: agents read it from
// disk instead (paying per-agent ingestion, but keeping requests well-formed).
const MAX_EMBED_BYTES = 200_000

const PROMPT_TEMPLATE = `You are a code reviewer. Your specific review focus is pre-assigned. Follow these steps exactly:

1. FIRST action — run this exact command with the Bash tool to receive your review focus:

   bash "__RUN_DIR__/claim_persona.sh"

   It prints your assigned focus, expertise, checklist, and known failure patterns. Conduct your entire review through that lens. If the command reports an error, stop immediately and report that error text as your entire review — do not improvise a focus. Do not read, list, or otherwise inspect anything inside __RUN_DIR__ other than running this command and, if step 2 below explicitly instructs it, reading the diff file it names.

2. The code changes to review:

### Changed files

__FILE_LIST__

### Commit messages

__COMMIT_LOG__

### Full diff

__FULL_DIFF__

3. Read the full diff carefully. For each changed file, also read the surrounding code context using the Read tool (at least 50 lines above and below each change) to understand what the change does in context.

4. Apply your assigned review checklist systematically. For each item, determine if the change introduces a risk.

5. Produce your review in this EXACT format:

**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / NONE

**Findings:**

For each finding:
- **[SEVERITY]** \`file:line\` — Description of the issue
  - Why it matters: explanation referencing known failure patterns if applicable
  - Suggestion: specific fix or mitigation

If no findings: "No issues found in my focus area."

**Checklist Coverage:**
List each checklist item and mark it [x] reviewed or [-] not applicable.
(Omit this section if your assigned focus says it has no formal checklist.)

**Summary:**
One paragraph summarizing your overall assessment.`

const FIRST_TEMPLATE = `export const meta = {
  name: 'qa-team-launch-first',
  description: 'Launch the first QA reviewer to warm the shared prompt prefix',
  phases: [{ title: 'First reviewer' }],
}
const PROMPT = __PROMPT_JSON__
phase('First reviewer')
const review = await agent(PROMPT, { label: 'reviewer-1', phase: 'First reviewer' })
return { reviews: [review || 'REVIEWER FAILED: reviewer-1 returned no review'] }
`

// Failed reviewers must stay visible as explicit sentinels — a silently shorter
// review list reads as complete coverage during synthesis.
const REST_TEMPLATE = `export const meta = {
  name: 'qa-team-launch-rest',
  description: 'Launch the remaining QA reviewers against the warmed prefix',
  phases: [{ title: 'Reviewers' }],
}
const PROMPT = __PROMPT_JSON__
phase('Reviewers')
const results = await parallel(
  Array.from({ length: __REST_COUNT__ }, (_, i) => () =>
    agent(PROMPT, { label: \`reviewer-\${i + 2}\`, phase: 'Reviewers' })
  )
)
const reviews = results.map((r, i) => r || \`REVIEWER FAILED: reviewer-\${i + 2} returned no review\`)
return { reviews }
`

function main() {
    if (process.argv.length !== 3) {
        console.error(`usage: node ${path.basename(process.argv[1])} <RUN_DIR>`)
        process.exit(1)
    }
    const runDir = path.resolve(process.argv[2])

    const fileList = fs.readFileSync(path.join(runDir, 'files.txt'), 'utf8').trim()
    const commitLog = fs.readFileSync(path.join(runDir, 'commits.txt'), 'utf8').trim()
    const reviewerCount = fs.readdirSync(path.join(runDir, 'personas')).filter((f) => f.endsWith('.md')).length
    if (reviewerCount < 2) {
        console.error('need at least 2 persona files in personas/ before building')
        process.exit(1)
    }

    const diffPath = path.join(runDir, 'diff.patch')
    const diffSize = fs.statSync(diffPath).size
    if (diffSize === 0) {
        console.error('diff.patch is empty — nothing to review')
        process.exit(1)
    }
    const fullDiff =
        diffSize > MAX_EMBED_BYTES
            ? `The diff is too large to inline. Read it from "${diffPath}" with the Read tool (in chunks if needed) before reviewing.`
            : fs.readFileSync(diffPath, 'utf8').trim()

    // Single-pass fill: every placeholder is substituted in one scan of the
    // original template, so placeholder-shaped text inside substituted content
    // (a diff that mentions __REST_COUNT__, a commit subject naming
    // __FULL_DIFF__) is never itself rewritten. The function replacement also
    // keeps `$&`-style patterns in diff content literal.
    const fill = (template, vars) =>
        template.replace(/__([A-Z_]+?)__/g, (match, key) => (key in vars ? vars[key] : match))

    const prompt = fill(PROMPT_TEMPLATE, {
        RUN_DIR: runDir,
        FILE_LIST: fileList,
        COMMIT_LOG: commitLog,
        FULL_DIFF: fullDiff,
    })
    // U+2028/U+2029 are valid in JSON strings but only valid in JS string
    // literals under ES2019 JSON-superset parsing — escape them so the
    // generated scripts parse under any dialect.
    const promptJson = JSON.stringify(prompt).replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029')

    fs.writeFileSync(path.join(runDir, 'launch_first.js'), fill(FIRST_TEMPLATE, { PROMPT_JSON: promptJson }))
    fs.writeFileSync(
        path.join(runDir, 'launch_rest.js'),
        fill(REST_TEMPLATE, { PROMPT_JSON: promptJson, REST_COUNT: String(reviewerCount - 1) })
    )
    console.info(`built ${runDir}/launch_first.js and ${runDir}/launch_rest.js for ${reviewerCount} reviewers`)
}

main()
