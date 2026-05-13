export function formatMoney(n: number | null | undefined): string {
    if (n == null || isNaN(n)) {
        return '—'
    }
    return '$' + Math.round(n).toLocaleString()
}

export function formatMoneyCompact(n: number | null | undefined): string {
    if (n == null || isNaN(n)) {
        return '—'
    }
    const abs = Math.abs(n)
    if (abs >= 1e9) {
        return `$${(n / 1e9).toFixed(2)}B`
    }
    if (abs >= 1e6) {
        return `$${(n / 1e6).toFixed(2)}M`
    }
    if (abs >= 1e3) {
        return `$${(n / 1e3).toFixed(1)}K`
    }
    return '$' + Math.round(n).toLocaleString()
}

export function daysUntil(iso: string | null | undefined): number | null {
    if (!iso) {
        return null
    }
    const m = String(iso)
        .slice(0, 10)
        .match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (!m) {
        return null
    }
    const target = Date.UTC(+m[1], +m[2] - 1, +m[3])
    const now = new Date()
    const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
    return Math.floor((target - today) / 86400000)
}

export function daysSince(ts: number | string | null | undefined): number | null {
    if (!ts) {
        return null
    }
    const parsed = typeof ts === 'number' ? ts : Date.parse(ts)
    if (isNaN(parsed)) {
        return null
    }
    return Math.floor((Date.now() - parsed) / 86400000)
}
