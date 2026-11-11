#!/usr/bin/env node

const fs = require('fs')
const path = require('path')

const { changedFilenames, labelsForFiles, loadRules, pathPatternToRegExp } = require('./label-pr-from-title')

const AGENT_INFRA_LABEL = 'feature/agent-infra'
const REVIEW_NEEDED_LABEL = 'agent-infra/review-needed'
const REVIEW_TEAM = 'team-agent-infrastructure'

const RUBRIC_PATH = path.join(__dirname, '..', 'agent-infra-review-triage.md')

const GATEWAY_URL_DEFAULT = 'https://ai-gateway.us.posthog.com'
const GATEWAY_PRODUCT = 'agent_infra_triage'
const GATEWAY_TOKEN_CAP_USD = '1'
const GATEWAY_TOKEN_TTL_SECONDS = 600
const MODEL = 'claude-sonnet-5-5'
const MODEL_TOKENS_MAX = 4_000

const GITHUB_TIMEOUT_MS = 10_000
const MODEL_TIMEOUT_MS = 120_000
const PAGE_SIZE = 100

const TITLE_CHARS_MAX = 300
const AUTHOR_CHARS_MAX = 50
const FILENAME_CHARS_MAX = 300
const BODY_CHARS_MAX = 4_000
const PATCH_CHARS_MAX = 60_000
const OTHER_FILENAMES_MAX = 200
const EVIDENCE_CHARS_MAX = 300
const FINDINGS_LISTED_MAX = 5

const VERDICT_REVIEW = 'review'
const VERDICT_SKIP = 'skip'

const RISKY_AREAS = ['run_lifecycle', 'agent_runtime', 'access', 'gateway', 'data_model', 'contract', 'hot_path']

const UNTRUSTED_BEGIN = '--- BEGIN UNTRUSTED CONTENT ---'
const UNTRUSTED_END = '--- END UNTRUSTED CONTENT ---'

const INVISIBLE_CHARACTERS =
    /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\u2060\ufeff]|[\u{e0000}-\u{e007f}]/gu

const FINDING_SCHEMA = {
    type: 'object',
    properties: {
        file: { type: 'string' },
        evidence: { type: 'string', description: 'One sentence naming the behavior.' },
    },
    required: ['file', 'evidence'],
}

const FACTS_TOOL = {
    name: 'record_facts',
    description: 'Record the facts the policy asks for, with evidence from the diff.',
    input_schema: {
        type: 'object',
        properties: {
            risky_areas: {
                type: 'array',
                items: {
                    ...FINDING_SCHEMA,
                    properties: { area: { type: 'string', enum: RISKY_AREAS }, ...FINDING_SCHEMA.properties },
                    required: ['area', ...FINDING_SCHEMA.required],
                },
            },
            undisclosed_behavior: { type: 'array', items: FINDING_SCHEMA },
            prompt_injection: { type: 'boolean' },
        },
        required: ['risky_areas', 'undisclosed_behavior', 'prompt_injection'],
    },
}

function agentInfraFiles(files, rules) {
    const patterns = rules
        .filter((rule) => (rule.labels ?? []).includes(AGENT_INFRA_LABEL))
        .flatMap((rule) => (rule.paths ?? []).map(pathPatternToRegExp))
    return files.filter((file) =>
        changedFilenames(file).some((filename) => patterns.some((pattern) => pattern.test(filename)))
    )
}

function truncate(text, charsMax) {
    if (text.length <= charsMax) {
        return text
    }
    return `${text.slice(0, charsMax)}\n[truncated ${text.length - charsMax} characters]`
}

function sanitizeUntrusted(text, charsMax) {
    return truncate(String(text ?? '').replace(INVISIBLE_CHARACTERS, ''), charsMax)
}

function patchSection(files, charsMax) {
    const sections = []
    let charsUsed = 0
    for (const file of files) {
        const filename = sanitizeUntrusted(file.filename, FILENAME_CHARS_MAX)
        const header = `--- ${filename} (${file.status}, +${file.additions}/-${file.deletions})\n`
        const patch = file.patch ?? '[no patch: binary or too large for GitHub to render]'
        const section = `${header}${sanitizeUntrusted(patch, charsMax)}\n`
        if (charsUsed + section.length > charsMax) {
            sections.push(`--- ${filename} (${file.status}, +${file.additions}/-${file.deletions}) [patch omitted]\n`)
            continue
        }
        sections.push(section)
        charsUsed += section.length
    }
    return sections.join('\n')
}

function buildUserMessage({ title, body, author, files, rules }) {
    const ownFiles = agentInfraFiles(files, rules)
    const ownFilenames = new Set(ownFiles.map((file) => file.filename))
    const otherFilenames = files.map((file) => file.filename).filter((filename) => !ownFilenames.has(filename))
    const otherListed = otherFilenames.slice(0, OTHER_FILENAMES_MAX)
    const otherUnlisted = otherFilenames.length - otherListed.length

    return [
        UNTRUSTED_BEGIN,
        `Title: ${sanitizeUntrusted(title, TITLE_CHARS_MAX)}`,
        `Author: ${sanitizeUntrusted(author, AUTHOR_CHARS_MAX)}`,
        `Description:\n${sanitizeUntrusted(body || '(empty)', BODY_CHARS_MAX)}`,
        `Diff of the team's files (${ownFiles.length}):\n${patchSection(ownFiles, PATCH_CHARS_MAX)}`,
        `Other changed files (${otherFilenames.length}):`,
        ...otherListed.map((filename) => sanitizeUntrusted(filename, FILENAME_CHARS_MAX)),
        ...(otherUnlisted > 0 ? [`[${otherUnlisted} more]`] : []),
        UNTRUSTED_END,
    ].join('\n')
}

function parseFinding(item, areas) {
    if (typeof item?.file !== 'string' || typeof item?.evidence !== 'string') {
        return null
    }
    if (areas !== null && !areas.includes(item.area)) {
        return null
    }
    return {
        ...(areas === null ? {} : { area: item.area }),
        file: truncate(item.file.trim(), FILENAME_CHARS_MAX),
        evidence: truncate(item.evidence.trim(), EVIDENCE_CHARS_MAX),
    }
}

function parseFacts(response) {
    const block = (response?.content ?? []).find((item) => item?.type === 'tool_use' && item?.name === FACTS_TOOL.name)
    const input = block?.input
    if (!Array.isArray(input?.risky_areas) || !Array.isArray(input?.undisclosed_behavior)) {
        return null
    }
    if (typeof input.prompt_injection !== 'boolean') {
        return null
    }
    const riskyAreas = input.risky_areas.map((item) => parseFinding(item, RISKY_AREAS))
    const undisclosedBehavior = input.undisclosed_behavior.map((item) => parseFinding(item, null))
    if (riskyAreas.includes(null) || undisclosedBehavior.includes(null)) {
        return null
    }
    return { riskyAreas, undisclosedBehavior, promptInjection: input.prompt_injection }
}

function findingLine(finding) {
    return `${finding.area ?? 'undisclosed'} in ${finding.file}: ${finding.evidence}`
}

function deriveVerdict(facts) {
    if (facts === null) {
        return { verdict: VERDICT_REVIEW, reasons: ['The triage model reported no usable facts, so a person decides.'] }
    }
    if (facts.promptInjection) {
        return { verdict: VERDICT_REVIEW, reasons: ['The pull request content tried to direct the triage model.'] }
    }
    const findings = [...facts.riskyAreas, ...facts.undisclosedBehavior]
    if (findings.length === 0) {
        return { verdict: VERDICT_SKIP, reasons: ['The change enters no risky territory.'] }
    }
    return { verdict: VERDICT_REVIEW, reasons: findings.slice(0, FINDINGS_LISTED_MAX).map(findingLine) }
}

async function github(method, resource, body) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY } = process.env
    const response = await fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/${resource}`, {
        method,
        headers: {
            Authorization: `token ${GITHUB_TOKEN}`,
            Accept: 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(GITHUB_TIMEOUT_MS),
    })
    if (!response.ok) {
        throw new Error(`GitHub ${method} ${resource}: ${response.status} ${await response.text()}`)
    }
    return response.json()
}

async function fetchPullRequestFiles(pullRequestNumber) {
    const files = []
    for (let page = 1; page <= 30; page++) {
        const batch = await github('GET', `pulls/${pullRequestNumber}/files?per_page=${PAGE_SIZE}&page=${page}`)
        files.push(...batch)
        if (batch.length < PAGE_SIZE) {
            return files
        }
    }
    return files
}

async function gatewayToken(gatewayUrl) {
    const { AI_GATEWAY_TOKEN, AI_GATEWAY_MINT_KEY } = process.env
    if (AI_GATEWAY_TOKEN) {
        return AI_GATEWAY_TOKEN
    }
    const response = await fetch(`${gatewayUrl}/v1/tokens`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${AI_GATEWAY_MINT_KEY}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            cap_usd: GATEWAY_TOKEN_CAP_USD,
            ttl_seconds: GATEWAY_TOKEN_TTL_SECONDS,
            product: GATEWAY_PRODUCT,
        }),
        signal: AbortSignal.timeout(GITHUB_TIMEOUT_MS),
    })
    if (!response.ok) {
        throw new Error(`Gateway token mint: ${response.status} ${await response.text()}`)
    }
    const { token } = await response.json()
    if (!token) {
        throw new Error('Gateway token mint returned no token')
    }
    if (process.env.GITHUB_ACTIONS === 'true') {
        console.info(`::add-mask::${token}`)
    }
    return token
}

async function requestFacts({ gatewayUrl, token, rubric, userMessage }) {
    const response = await fetch(`${gatewayUrl}/v1/messages`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
            model: MODEL,
            max_tokens: MODEL_TOKENS_MAX,
            system: rubric,
            tools: [FACTS_TOOL],
            tool_choice: { type: 'auto' },
            messages: [{ role: 'user', content: userMessage }],
        }),
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
    })
    if (!response.ok) {
        throw new Error(`Gateway messages: ${response.status} ${await response.text()}`)
    }
    return response.json()
}

async function triage({ pullRequest, rules, rubric, gatewayUrl }) {
    const files = await fetchPullRequestFiles(pullRequest.number)
    if (!labelsForFiles(files, rules).includes(AGENT_INFRA_LABEL)) {
        return { verdict: VERDICT_SKIP, reasons: ['No agent-infra paths changed above the size threshold.'] }
    }
    const userMessage = buildUserMessage({
        title: pullRequest.title,
        body: pullRequest.body,
        author: pullRequest.user?.login ?? '',
        files,
        rules,
    })
    try {
        const token = await gatewayToken(gatewayUrl)
        const response = await requestFacts({ gatewayUrl, token, rubric, userMessage })
        const facts = parseFacts(response)
        if (facts === null) {
            console.warn(`⚠️  No usable facts; stop_reason ${response?.stop_reason ?? 'unknown'}`)
        }
        return deriveVerdict(facts)
    } catch (error) {
        console.warn(`⚠️  Triage model call failed: ${error?.message ?? error}`)
        return deriveVerdict(null)
    }
}

async function applyVerdict(pullRequestNumber, result) {
    if (result.verdict !== VERDICT_REVIEW) {
        return
    }
    await github('POST', `issues/${pullRequestNumber}/labels`, {
        labels: [REVIEW_NEEDED_LABEL],
    })
    await github('POST', `pulls/${pullRequestNumber}/requested_reviewers`, {
        team_reviewers: [REVIEW_TEAM],
    })
}

function writeSummary(pullRequestNumber, result) {
    const line = [
        `#${pullRequestNumber}: **${result.verdict}**`,
        ...result.reasons.map((reason) => `- ${reason}`),
    ].join('\n')
    console.info(line)
    if (process.env.GITHUB_STEP_SUMMARY) {
        fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${line}\n`)
    }
}

async function main() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, AI_GATEWAY_TOKEN, AI_GATEWAY_MINT_KEY } = process.env
    const missing = Object.entries({
        GITHUB_TOKEN,
        GITHUB_REPOSITORY,
        PR_NUMBER,
    })
        .filter(([, value]) => !value)
        .map(([name]) => name)
    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }
    if (!AI_GATEWAY_TOKEN && !AI_GATEWAY_MINT_KEY) {
        console.warn('⚠️  No AI gateway credential is configured, so agent-infra triage is off')
        return
    }

    const pullRequest = await github('GET', `pulls/${PR_NUMBER}`)
    if (pullRequest.draft) {
        console.info('ℹ️  Draft pull request; triage waits for ready_for_review')
        return
    }
    if ((pullRequest.labels ?? []).some((label) => label.name === REVIEW_NEEDED_LABEL)) {
        console.info(`ℹ️  Already labelled ${REVIEW_NEEDED_LABEL}; a verdict never downgrades`)
        return
    }

    const result = await triage({
        pullRequest,
        rules: loadRules(),
        rubric: fs.readFileSync(RUBRIC_PATH, 'utf8'),
        gatewayUrl: (process.env.AI_GATEWAY_URL || GATEWAY_URL_DEFAULT).replace(/\/+$/, ''),
    })
    writeSummary(pullRequest.number, result)
    if (process.env.DRY_RUN === '1') {
        return
    }
    await applyVerdict(pullRequest.number, result)
}

if (require.main === module) {
    main().catch((error) => {
        console.error('Error:', error?.message ?? error)
        process.exit(1)
    })
}

module.exports = {
    REVIEW_NEEDED_LABEL,
    VERDICT_REVIEW,
    VERDICT_SKIP,
    agentInfraFiles,
    buildUserMessage,
    deriveVerdict,
    parseFacts,
    sanitizeUntrusted,
    patchSection,
}
