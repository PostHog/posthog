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
// `noBaseline` overrides the wording when there is nothing to compare against (the
// eager-graph section prefers "no base measurement" over treating the value as new).
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

// Map a numeric change to a ci-report status: growth warns, shrink/flat is ok, and a
// missing baseline is informational (no delta to judge).
export function deltaStatus(delta, hasBaseline) {
    if (!hasBaseline) {
        return 'info'
    }
    return delta > 0 ? 'warn' : 'ok'
}
