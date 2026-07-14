export function formatBytes(bytes) {
    const abs = Math.abs(bytes)
    if (abs >= 1024 * 1024) {
        return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
    }
    if (abs >= 1024) {
        return `${(bytes / 1024).toFixed(1)} KiB`
    }
    return `${bytes} B`
}

// Human-readable change vs a baseline, with an at-a-glance arrow. Used verbatim in the
// header summary and the section table so a reader sees the same phrasing in both.
// `noBaseline` overrides the wording when there is nothing to compare against.
export function formatDelta(bytes, baselineBytes, { noBaseline } = {}) {
    if (baselineBytes === undefined || baselineBytes === null) {
        return noBaseline ?? `🔺 +${formatBytes(bytes)} (new)`
    }
    const delta = bytes - baselineBytes
    if (delta === 0) {
        return 'no change'
    }
    const sign = delta > 0 ? '+' : '-'
    const magnitude = `${delta > 0 ? '🔺' : '🟢'} ${sign}${formatBytes(Math.abs(delta))}`
    if (baselineBytes === 0) {
        return `${magnitude} (new)`
    }
    const percent = ((Math.abs(delta) / baselineBytes) * 100).toFixed(1)
    return `${magnitude} (${sign}${percent}%)`
}

// One total compared against the base branch: the body line, header summary, and status
// for a size section, with the missing-baseline presentation handled once — growth warns,
// shrink/flat is ok, and no baseline is informational rather than a bogus "new" delta.
export function totalComparison(bytes, baselineBytes) {
    if (baselineBytes === null || baselineBytes === undefined) {
        return {
            status: 'info',
            summary: 'no base branch to compare',
            totalLine: `**Total:** ${formatBytes(bytes)} _(no base branch measurement to compare against yet)_`,
        }
    }
    return {
        status: bytes > baselineBytes ? 'warn' : 'ok',
        summary: formatDelta(bytes, baselineBytes),
        totalLine: `**Total:** ${formatBytes(bytes)} · ${formatDelta(bytes, baselineBytes)}`,
    }
}
