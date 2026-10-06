import { fileURLToPath } from 'node:url'

import { DRY_RUN, GITHUB_REPOSITORY, GITHUB_SERVER_URL, editWorkflowBlock, postToSlack } from './weekly-report-common.mjs'

const DASHBOARD_TITLE = process.env.RENOVATE_DASHBOARD_TITLE || 'Renovate: Dependency Status'
const TEAM_DEVEX_CHANNEL = 'C09G8QA6740'
const CONFIG_PATH = '.github/renovate.json5'

function count(body, pattern) {
    return [...body.matchAll(pattern)].length
}

function section(body, heading) {
    const start = body.indexOf(`## ${heading}`)
    if (start === -1) {
        return ''
    }
    const end = body.indexOf('\n## ', start + 1)
    return body.slice(start, end === -1 ? undefined : end)
}

// Renovate reads the same `<!-- action-branch=name -->` markers back to learn which boxes are ticked,
// so they are a steadier contract than the surrounding prose.
export function parseDashboard(body) {
    const pendingTitles = [...body.matchAll(/<!-- approve-branch=\S+ -->(.*)/g)].map((match) => match[1])
    const cves = section(body, 'Vulnerabilities').match(/`(\d+)`\/`(\d+)`/)
    return {
        pending: pendingTitles.length,
        pendingMajor: pendingTitles.filter((title) => /\bto v\d+$/.test(title.trim())).length,
        open: count(body, /<!-- rebase-branch=\S+ -->/g),
        errored: count(body, /<!-- retry-branch=\S+ -->/g),
        deprecated: count(section(body, 'Deprecations / Replacements'), /^\| (?!Datasource |-)/gm),
        cves: cves ? { fixable: Number(cves[1]), total: Number(cves[2]) } : null,
        configMigrationNeeded: body.includes('## Config Migration Needed'),
        truncated: /body was truncated/.test(body),
    }
}

export function buildBlocks(summary, dashboardUrl) {
    const atLeast = summary.truncated ? '+' : ''
    const major = summary.pendingMajor > 0 ? ` (${summary.pendingMajor}${atLeast} major)` : ''
    const lines = [
        `• ${summary.pending}${atLeast} updates waiting for approval${major}`,
        summary.cves && `• ${summary.cves.total} known CVEs, ${summary.cves.fixable} with a fix available`,
        summary.deprecated > 0 && `• ${summary.deprecated} deprecated or replaced dependencies`,
        summary.open > 0 && `• ${summary.open} Renovate PRs open`,
        summary.errored > 0 && `• ${summary.errored} updates failed and will be retried`,
        summary.configMigrationNeeded && `• \`${CONFIG_PATH}\` uses renamed options and needs a migration`,
        summary.truncated &&
            "• The dashboard hit GitHub's issue size limit, so these counts are a lower bound and sections below the cut are missing",
    ].filter(Boolean)
    const repoUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}`
    const links = [
        `<${dashboardUrl}|Dashboard>`,
        `<https://developer.mend.io/github/${GITHUB_REPOSITORY}|Job logs>`,
        `<${repoUrl}/blob/master/${CONFIG_PATH}|Config>`,
    ].join(' · ')
    return [
        { type: 'header', text: { type: 'plain_text', text: 'Renovate dependency status' } },
        { type: 'section', text: { type: 'mrkdwn', text: lines.join('\n') } },
        { type: 'context', elements: [{ type: 'mrkdwn', text: links }] },
        editWorkflowBlock(),
    ].filter(Boolean)
}

async function fetchDashboard() {
    const url = `https://api.github.com/repos/${GITHUB_REPOSITORY}/issues?creator=${encodeURIComponent('app/renovate')}&state=open&per_page=100`
    const res = await fetch(url, {
        headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json' },
    })
    if (!res.ok) {
        throw new Error(`GitHub issues list -> ${res.status}: ${await res.text()}`)
    }
    const issue = (await res.json()).find((candidate) => candidate.title === DASHBOARD_TITLE)
    if (!issue) {
        throw new Error(`No open "${DASHBOARD_TITLE}" issue by app/renovate in ${GITHUB_REPOSITORY}`)
    }
    return issue
}

async function main() {
    const issue = await fetchDashboard()
    const summary = parseDashboard(issue.body || '')
    const blocks = buildBlocks(summary, issue.html_url)
    if (DRY_RUN) {
        console.info(JSON.stringify({ summary, blocks }, null, 2))
        return
    }
    await postToSlack(blocks, `Renovate: ${summary.pending} updates waiting for approval`, {
        channel: process.env.SLACK_CHANNEL || TEAM_DEVEX_CHANNEL,
    })
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    await main()
}
