#!/usr/bin/env node
// Posts the frontend layers section of the CI report. It compares the PR's layer report with the base's,
// not with layer-baseline.txt, so an upward import that a PR also adds to the baseline still shows.
// CI copies this file before it resets the workspace to the base branch, so it may import only modules
// that already exist on the base: no layers.mjs, and the layer order comes from the report itself.
import { formatBytes, formatDelta } from './ci-report/format.mjs'

const MAX_LISTED = 20

export function compareLayerReports(report, baseReport) {
    const baseUpward = new Set(baseReport?.upward ?? [])
    const prUpward = new Set(report.upward)
    return {
        added: baseReport ? report.upward.filter((edge) => !baseUpward.has(edge)) : [],
        removed: baseReport ? baseReport.upward.filter((edge) => !prUpward.has(edge)) : [],
        layers: report.layers.map((layer) => ({
            layer,
            bytes: report.eagerBytes[layer],
            baseBytes: baseReport?.eagerBytes?.[layer],
        })),
    }
}

// Edge and chain paths come from the PR's own build output, so a crafted file name could carry
// a newline or an HTML comment delimiter and forge the CI report's own section markers.
const sanitizeForReport = (text) =>
    text
        .replace(/[\r\n]/g, ' ')
        .replace(/<!--/g, '< !--')
        .replace(/-->/g, '-- >')
const shortName = (file) => sanitizeForReport(file.replace(/^frontend\/src\//, ''))

export function renderLayerSection(report, baseReport, graphUrl) {
    const { added, removed, layers } = compareLayerReports(report, baseReport)
    const lines = [
        'Static imports from a lower frontend layer into a higher one (layers, lowest first: ' +
            `${report.layers.join(', ')}). Compared with the base branch, so an import that a PR also adds to ` +
            '`layer-baseline.txt` still shows here. Sizes are the source bytes on the eager path of every logged-in page.',
        '',
        '| Layer | Eager source bytes | Δ vs base |',
        '| --- | --- | --- |',
        ...layers.map(
            ({ layer, bytes, baseBytes }) =>
                `| ${layer} | ${formatBytes(bytes)} | ${formatDelta(bytes, baseBytes, { noBaseline: '_(no base measurement)_' })} |`
        ),
        '',
    ]
    if (!baseReport) {
        lines.push('ℹ️ No base report, so new and removed imports are not listed.', '')
    }
    for (const edge of added.slice(0, MAX_LISTED)) {
        const [from] = edge.split(' -> ')
        const chain = report.eagerChains?.[from]
        lines.push(`🟡 New upward import: \`${edge.split(' -> ').map(shortName).join(' -> ')}\``)
        if (chain) {
            lines.push(
                '',
                'It is on the eager path of every logged-in page:',
                '',
                '```',
                chain.map(shortName).join('\n  -> '),
                '```'
            )
        }
        lines.push('')
    }
    if (added.length > MAX_LISTED) {
        lines.push(`…and ${added.length - MAX_LISTED} more.`, '')
    }
    if (added.length) {
        lines.push(
            'Load the higher layer with `lazyWithRetry()` or `retryImport(() => import(...))`, or move the shared code down a layer.',
            ''
        )
    }
    if (removed.length) {
        lines.push(
            `🟢 ${removed.length} upward import(s) removed. Run \`hogli lint:frontend-layers --prune-baseline\` if CI asks.`,
            ''
        )
    }
    if (graphUrl) {
        lines.push(`[Download the interactive layer graph](${graphUrl}) for this PR.`, '')
    }
    lines.push(
        '<sub>Posted automatically by [check-layers](https://github.com/PostHog/posthog/blob/master/frontend/bin/check-layers.mjs)</sub>'
    )
    // Without a base there is no comparison, so a new upward import must not read as a pass.
    if (!baseReport) {
        return { status: 'info', summary: 'no base comparison available', body: lines.join('\n') }
    }
    const summary = added.length
        ? `${added.length} new upward import(s)`
        : `no new upward imports, ${removed.length} removed`
    return { status: added.length ? 'warn' : 'ok', summary, body: lines.join('\n') }
}

async function main() {
    const [{ resolvePrAndBaseReport }, { postSection }] = await Promise.all([
        import('./ci-report/report-files.mjs'),
        import('./ci-report/update-ci-report.mjs'),
    ])
    const resolved = resolvePrAndBaseReport('layer-report', 'frontend layers')
    if (resolved) {
        await postSection({
            id: 'frontend-layers',
            ...renderLayerSection(resolved.report, resolved.baseReport, process.env.LAYER_GRAPH_URL),
        })
    }
}

// The CI helpers load only when this runs as a script, so jest can import the functions above.
if (/post-layer-comment(-pr)?\.mjs$/.test(process.argv[1] ?? '')) {
    main().catch((error) => {
        console.error(error)
        process.exit(1)
    })
}
