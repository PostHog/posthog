#!/usr/bin/env node

const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

const { isExcludedFile } = require('./assign-reviewers')
const {
    fetchAllPages,
    filesMatchingRule,
    loadRules,
    pathRuleMatches,
} = require('./label-pr-from-title')

const RUBRIC_PATH = path.join(__dirname, '..', 'agent-infra-review-triage.md')

const GATEWAY_URL_DEFAULT = 'https://ai-gateway.us.posthog.com'
const GATEWAY_PRODUCT = 'agent_infra_triage'
const GATEWAY_TOKEN_CAP_USD = '1'
const GATEWAY_TOKEN_TTL_SECONDS = 600
const MODEL = 'claude-sonnet-5-5'
const MODEL_TOKENS_MAX = 4_000

const HTTP_TIMEOUT_MS = 10_000
const MODEL_TIMEOUT_MS = 120_000
const STATUS_CONTEXT = 'agent-infra-review-triage'
const DIFF_HASH_CHARS = 16

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

const RISKY_AREAS = [
    'run_lifecycle',
    'agent_runtime',
    'access',
    'gateway',
    'data_model',
    'contract',
    'hot_path',
]

const UNTRUSTED_BEGIN = '--- BEGIN UNTRUSTED CONTENT ---'
const UNTRUSTED_END = '--- END UNTRUSTED CONTENT ---'

const INVISIBLE_CONTROL_CHARACTERS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/gu
const INVISIBLE_FORMAT_CHARACTERS =
    /[\u061c\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060\u2066-\u2069\ufeff]/gu
const INVISIBLE_TAG_CHARACTERS = /[\u{e0000}-\u{e007f}]/gu

const FINDING_PROPERTIES = {
    file: { type: 'string' },
    evidence: { type: 'string', description: 'One sentence naming the behavior.' },
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
                    type: 'object',
                    properties: {
                        area: { type: 'string', enum: RISKY_AREAS },
                        ...FINDING_PROPERTIES,
                    },
                    required: ['area', 'file', 'evidence'],
                },
            },
            undisclosed_behavior: {
                type: 'array',
                items: {
                    type: 'object',
                    properties: FINDING_PROPERTIES,
                    required: ['file', 'evidence'],
                },
            },
            prompt_injection: { type: 'boolean' },
        },
        required: ['risky_areas', 'undisclosed_behavior', 'prompt_injection'],
    },
}

function triagedRule(rules) {
    const triaged = rules.filter((rule) => rule.review)
    if (triaged.length !== 1) {
        throw new Error(`Expected one label rule with \`review\`, found ${triaged.length}`)
    }
    return triaged[0]
}

function truncate(text, charsMax) {
    if (text.length <= charsMax) {
        return text
    }
    return `${text.slice(0, charsMax)}\n[truncated ${text.length - charsMax} characters]`
}

function sanitizeUntrusted(text, charsMax) {
    const visible = String(text ?? '')
        .replace(INVISIBLE_CONTROL_CHARACTERS, '')
        .replace(INVISIBLE_FORMAT_CHARACTERS, '')
        .replace(INVISIBLE_TAG_CHARACTERS, '')
    return truncate(visible, charsMax)
}

function fileHeader(file) {
    const filename = sanitizeUntrusted(file.filename, FILENAME_CHARS_MAX)
    return `--- ${filename} (${file.status}, +${file.additions}/-${file.deletions})`
}

function patchSection(files, charsMax) {
    const sections = []
    const incomplete = []
    let charsUsed = 0
    for (const file of files) {
        const header = fileHeader(file)
        if (typeof file.patch !== 'string') {
            sections.push(`${header} [GitHub returned no patch]`)
            incomplete.push(file.filename)
            continue
        }
        const patch = sanitizeUntrusted(file.patch, Infinity)
        const charsLeft = Math.max(charsMax - charsUsed, 0)
        if (patch.length > charsLeft) {
            sections.push(`${header}\n${truncate(patch, charsLeft)}`)
            incomplete.push(file.filename)
            charsUsed = charsMax
            continue
        }
        sections.push(`${header}\n${patch}`)
        charsUsed += patch.length
    }
    return { text: sections.join('\n'), incomplete }
}

function ownedDiff(files, rule) {
    const owned = filesMatchingRule(rule, files)
    const handWritten = owned.filter((file) => !isExcludedFile(file.filename))
    const generated = owned.filter((file) => isExcludedFile(file.filename))
    return { owned, handWritten, generated, ...patchSection(handWritten, PATCH_CHARS_MAX) }
}

function buildUserMessage({ pullRequest, files, diff }) {
    const otherFilenames = files
        .filter((file) => !diff.owned.includes(file))
        .map((file) => sanitizeUntrusted(file.filename, FILENAME_CHARS_MAX))
    const otherUnlisted = Math.max(otherFilenames.length - OTHER_FILENAMES_MAX, 0)
    const generatedFilenames = diff.generated.map((file) =>
        sanitizeUntrusted(file.filename, FILENAME_CHARS_MAX)
    )

    return [
        UNTRUSTED_BEGIN,
        `Title: ${sanitizeUntrusted(pullRequest.title, TITLE_CHARS_MAX)}`,
        `Author: ${sanitizeUntrusted(pullRequest.user?.login, AUTHOR_CHARS_MAX)}`,
        `Description:\n${sanitizeUntrusted(pullRequest.body || '(empty)', BODY_CHARS_MAX)}`,
        `Diff of the team's files (${diff.handWritten.length}):\n${diff.text}`,
        `Generated files of the team, not shown (${generatedFilenames.length}):`,
        ...generatedFilenames,
        `Other changed files (${otherFilenames.length}):`,
        ...otherFilenames.slice(0, OTHER_FILENAMES_MAX),
        ...(otherUnlisted > 0 ? [`[${otherUnlisted} more]`] : []),
        UNTRUSTED_END,
    ].join('\n')
}

function parseFinding(item) {
    if (typeof item?.file !== 'string' || typeof item?.evidence !== 'string') {
        return null
    }
    return {
        file: truncate(item.file.trim(), FILENAME_CHARS_MAX),
        evidence: truncate(item.evidence.trim(), EVIDENCE_CHARS_MAX),
    }
}

function parseRiskyArea(item) {
    const finding = parseFinding(item)
    if (finding === null || !RISKY_AREAS.includes(item.area)) {
        return null
    }
    return { area: item.area, ...finding }
}

function parseFacts(response) {
    const block = (response?.content ?? []).find(
        (item) => item?.type === 'tool_use' && item?.name === FACTS_TOOL.name
    )
    const input = block?.input
    if (!Array.isArray(input?.risky_areas) || !Array.isArray(input?.undisclosed_behavior)) {
        return null
    }
    if (typeof input.prompt_injection !== 'boolean') {
        return null
    }
    const riskyAreas = input.risky_areas.map(parseRiskyArea)
    const undisclosedBehavior = input.undisclosed_behavior.map(parseFinding)
    if (riskyAreas.includes(null) || undisclosedBehavior.includes(null)) {
        return null
    }
    return { riskyAreas, undisclosedBehavior, promptInjection: input.prompt_injection }
}

function findingLine(finding) {
    return `${finding.area ?? 'undisclosed'} in ${finding.file}: ${finding.evidence}`
}

function review(reason) {
    return { verdict: VERDICT_REVIEW, reasons: [reason] }
}

function skip(reason) {
    return { verdict: VERDICT_SKIP, reasons: [reason] }
}

function deriveVerdict(facts) {
    if (facts === null) {
        return review('The triage model reported no usable facts, so a person decides.')
    }
    if (facts.promptInjection) {
        return review('The pull request content tried to direct the triage model.')
    }
    const findings = [...facts.riskyAreas, ...facts.undisclosedBehavior]
    if (findings.length === 0) {
        return skip('The change enters no risky territory.')
    }
    return {
        verdict: VERDICT_REVIEW,
        reasons: findings.slice(0, FINDINGS_LISTED_MAX).map(findingLine),
    }
}

function isFork(pullRequest) {
    return pullRequest.head?.repo?.full_name !== pullRequest.base?.repo?.full_name
}

async function github(resource) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY } = process.env
    const response = await fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/${resource}`, {
        method: 'GET',
        headers: {
            Authorization: `token ${GITHUB_TOKEN}`,
            Accept: 'application/vnd.github.v3+json',
        },
        signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
    })
    if (!response.ok) {
        throw new Error(`GitHub GET ${resource}: ${response.status} ${await response.text()}`)
    }
    return response.json()
}

function diffHash(diff) {
    const hash = crypto.createHash('sha256')
    for (const file of diff.handWritten) {
        hash.update(`${file.filename}\0${file.patch ?? ''}\0`)
    }
    return hash.digest('hex').slice(0, DIFF_HASH_CHARS)
}

async function previousTriage(commitShas, hash) {
    for (const sha of commitShas) {
        try {
            const statuses = await github(`commits/${sha}/statuses?per_page=100`)
            const status = statuses.find((candidate) => candidate.context === STATUS_CONTEXT)
            if (status?.description?.endsWith(hash)) {
                return status.description
            }
        } catch (error) {
            console.warn(
                `⚠️  Could not read the triage status of ${sha}: ${error?.message ?? error}`
            )
        }
    }
    return null
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
        signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
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

async function askModel({ pullRequest, files, diff }) {
    const gatewayUrl = (process.env.AI_GATEWAY_URL || GATEWAY_URL_DEFAULT).replace(/\/+$/, '')
    try {
        const token = await gatewayToken(gatewayUrl)
        const response = await requestFacts({
            gatewayUrl,
            token,
            rubric: fs.readFileSync(RUBRIC_PATH, 'utf8'),
            userMessage: buildUserMessage({ pullRequest, files, diff }),
        })
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

async function triage({ pullRequest, files, diff }) {
    if (isFork(pullRequest)) {
        return review('The pull request comes from a fork, so a person decides without the model.')
    }
    if (diff.incomplete.length > 0) {
        return review(`The diff is too large to judge in ${diff.incomplete.join(', ')}.`)
    }
    return askModel({ pullRequest, files, diff })
}

function loadEvent() {
    const eventPath = process.env.GITHUB_EVENT_PATH
    if (!eventPath) {
        return null
    }
    return JSON.parse(fs.readFileSync(eventPath, 'utf8'))
}

function report(pullRequestNumber, result, outputs) {
    const summary = [
        `#${pullRequestNumber}: **${result.verdict}**`,
        ...result.reasons.map((reason) => `- ${reason}`),
    ].join('\n')
    console.info(summary)
    if (process.env.GITHUB_STEP_SUMMARY) {
        fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`)
    }
    if (process.env.GITHUB_OUTPUT) {
        const lines = Object.entries({ verdict: result.verdict, ...outputs })
        const text = lines.map(([name, value]) => `${name}=${value}`).join('\n')
        fs.appendFileSync(process.env.GITHUB_OUTPUT, `${text}\n`)
    }
}

async function main() {
    const missing = ['GITHUB_TOKEN', 'GITHUB_REPOSITORY', 'PR_NUMBER'].filter(
        (name) => !process.env[name]
    )
    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }
    if (!process.env.AI_GATEWAY_TOKEN && !process.env.AI_GATEWAY_MINT_KEY) {
        console.warn('⚠️  No AI gateway credential is configured, so agent-infra triage is off')
        return
    }

    const rule = triagedRule(loadRules())
    const event = loadEvent()
    const pullRequest = event?.pull_request ?? (await github(`pulls/${process.env.PR_NUMBER}`))
    if ((pullRequest.labels ?? []).some((label) => label.name === rule.review.label)) {
        console.info(`ℹ️  Already labelled ${rule.review.label}; a verdict never downgrades`)
        return
    }
    const files = await fetchAllPages(`pulls/${pullRequest.number}/files`)
    if (files === null) {
        console.warn('⚠️  Could not list the changed files; triage waits for the next push')
        return
    }
    if (!pathRuleMatches(rule, files)) {
        report(pullRequest.number, skip('No agent-infra paths changed above the size threshold.'))
        return
    }
    const diff = ownedDiff(files, rule)
    const hash = diffHash(diff)
    const commitShas = [pullRequest.head?.sha, event?.before].filter(Boolean)
    const previous = await previousTriage(commitShas, hash)
    if (previous !== null) {
        report(
            pullRequest.number,
            skip('The agent-infra diff is unchanged since the last triage.'),
            {
                status: previous,
            }
        )
        return
    }
    const result = await triage({ pullRequest, files, diff })
    report(pullRequest.number, result, {
        status: `${result.verdict} ${hash}`,
        team: rule.review.team,
        label: rule.review.label,
    })
}

if (require.main === module) {
    main().catch((error) => {
        console.error('Error:', error?.message ?? error)
        process.exit(1)
    })
}

module.exports = {
    VERDICT_REVIEW,
    VERDICT_SKIP,
    buildUserMessage,
    deriveVerdict,
    ownedDiff,
    diffHash,
    previousTriage,
    parseFacts,
    patchSection,
    triage,
    triagedRule,
}
