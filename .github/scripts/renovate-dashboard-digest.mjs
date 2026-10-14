import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

import {
    DRY_RUN,
    GITHUB_REPOSITORY,
    GITHUB_SERVER_URL,
    cell,
    editWorkflowBlock,
    postToSlack,
} from './weekly-report-common.mjs'

const ALERTS_DEVEX_CHANNEL = 'C0AS64N6DJL'
const CONFIG_PATH = '.github/renovate.json5'
const ECOSYSTEMS = { npm: 'npm', pep621: 'python', cargo: 'rust', gomod: 'go', 'github-actions': 'actions' }
const UPDATE_TYPES = ['major', 'minor', 'patch']
const COLUMNS = [...UPDATE_TYPES, 'other', 'total']

export function summarize(report) {
    const repository = Object.values(report.repositories ?? {})[0]
    const branches = new Map()
    const deprecated = new Set()
    const lookupWarnings = new Set()
    for (const [manager, packageFiles] of Object.entries(repository?.packageFiles ?? {})) {
        for (const dep of packageFiles.flatMap((packageFile) => packageFile.deps)) {
            const depKey = `${manager}:${dep.depName}`
            if (dep.deprecationMessage) {
                deprecated.add(depKey)
            }
            if (dep.warnings?.length) {
                lookupWarnings.add(depKey)
            }
            for (const update of dep.updates ?? []) {
                const branch = branches.get(update.branchName) ?? { manager, types: new Set() }
                branch.types.add(update.updateType)
                branches.set(update.branchName, branch)
            }
        }
    }
    const pending = {}
    for (const { manager, types } of branches.values()) {
        const type = UPDATE_TYPES.find((candidate) => types.has(candidate)) ?? 'other'
        pending[manager] ??= Object.fromEntries(COLUMNS.map((column) => [column, 0]))
        pending[manager][type] += 1
        pending[manager].total += 1
    }
    // Renovate exits 0 when a lookup aborts.
    if (branches.size === 0) {
        throw new Error('The Renovate report lists no pending updates, so the lookup did not complete')
    }
    return { pending, deprecated: deprecated.size, lookupWarnings: lookupWarnings.size }
}

export function buildBlocks({ pending, deprecated, lookupWarnings }, day) {
    const managers = Object.keys(pending).sort((a, b) => pending[b].total - pending[a].total)
    const totals = Object.fromEntries(
        COLUMNS.map((column) => [column, managers.reduce((sum, manager) => sum + pending[manager][column], 0)])
    )
    const row = (label, counts) => [cell(label), ...COLUMNS.map((column) => cell(counts[column].toLocaleString('en-US')))]
    const repoUrl = `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}`
    const footer = [
        `${deprecated} deprecated`,
        `${lookupWarnings} lookup warnings`,
        `<${repoUrl}/issues?q=${encodeURIComponent('is:issue is:open author:app/renovate')}|dashboard>`,
        `<https://developer.mend.io/github/${GITHUB_REPOSITORY}|job logs>`,
        `<${repoUrl}/blob/master/${CONFIG_PATH}|config>`,
    ].join(' · ')
    return [
        {
            type: 'section',
            text: { type: 'mrkdwn', text: `*Weekly Renovate, ${day}* _(pending dependency updates)_` },
        },
        {
            type: 'table',
            column_settings: [{ align: 'left' }, ...COLUMNS.map(() => ({ align: 'right' }))],
            rows: [
                [cell('ecosystem'), ...COLUMNS.map(cell)],
                ...managers.map((manager) => row(ECOSYSTEMS[manager] ?? manager, pending[manager])),
                row('all', totals),
            ],
        },
        { type: 'context', elements: [{ type: 'mrkdwn', text: footer }] },
        editWorkflowBlock(),
    ].filter(Boolean)
}

async function main() {
    const summary = summarize(JSON.parse(readFileSync(process.env.RENOVATE_REPORT_PATH, 'utf8')))
    const blocks = buildBlocks(summary, new Date().toISOString().slice(0, 10))
    if (DRY_RUN) {
        console.info(JSON.stringify(blocks, null, 2))
        return
    }
    await postToSlack(blocks, 'Weekly Renovate digest', { channel: process.env.SLACK_CHANNEL || ALERTS_DEVEX_CHANNEL })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
