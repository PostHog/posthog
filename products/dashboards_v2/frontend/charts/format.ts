const SI = ['', 'k', 'M', 'G', 'T', 'P']
const BYTES = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']

export function formatValue(
    v: number | null | undefined,
    unitOrNull?: string | null,
    decimalsOrNull?: number | null
): string {
    const unit = unitOrNull ?? undefined
    const decimals = decimalsOrNull ?? undefined
    if (v === null || v === undefined || Number.isNaN(v)) {
        return '–'
    }
    if (v === 0 && (unit === 's' || unit === 'ms')) {
        return `0 ${unit}`
    }
    const d = decimals
    switch (unit) {
        case 'By':
        case 'bytes': {
            let i = 0
            let x = Math.abs(v)
            while (x >= 1024 && i < BYTES.length - 1) {
                x /= 1024
                i++
            }
            return `${sign(v)}${trim(x, d, i ? 1 : 0)} ${BYTES[i]}`
        }
        case 'Bps':
        case 'binBps':
            return `${formatValue(v, 'By', d)}/s`
        case 'decbytes': {
            const s = short(v, d)
            return `${s}${/[kMGTP]$/.test(s) ? '' : ' '}B`
        }
        case 'deckbytes':
            return formatValue(v * 1e3, 'decbytes', d)
        case 'decmbytes':
            return formatValue(v * 1e6, 'decbytes', d)
        case 'decgbytes':
            return formatValue(v * 1e9, 'decbytes', d)
        case 'kbytes':
            return formatValue(v * 1024, 'bytes', d)
        case 'mbytes':
            return formatValue(v * 1024 ** 2, 'bytes', d)
        case 'gbytes':
            return formatValue(v * 1024 ** 3, 'bytes', d)
        case 'bps':
            return `${short(v, d)}b/s`
        case '%':
        case 'percent':
            return `${trim(v, d, 1)}%`
        case 'percentunit':
            return `${trim(v * 100, d, 1)}%`
        case 's':
        case 'dtdurations':
            return duration(v * 1000, d)
        case 'ms':
        case 'dtdurationms':
            return duration(v, d)
        case 'µs':
            return duration(v / 1000, d)
        case 'ns':
            return duration(v / 1e6, d)
        case 'currencyUSD':
            return `${sign(v)}$${short(Math.abs(v), d ?? 2)}`
        case 'short':
        case 'sishort':
        case 'none':
            return short(v, d)
        case 'reqpm':
            return `${short(v, d)} req/min`
        case 'cps':
            return `${short(v, d)}/s`
        case 'cores':
            return `${trim(v, d, 2)} cores`
        case 'req/s':
        case 'rps':
            return `${short(v, d)} req/s`
        case 'ops':
            return `${short(v, d)} ops`
        case 'locale':
            return full(v, d)
        default:
            if (unit?.startsWith('prefix:')) {
                const [pre, suf = ''] = unit.slice(7).split('|suffix:')
                return `${sign(v)}${pre}${full(Math.abs(v), d)}${suf}`
            }
            if (unit?.startsWith('suffix:')) {
                return `${full(v, d)}${unit.slice(7)}`
            }
            if (unit?.startsWith('count:')) {
                return `${short(v, d)} ${unit.slice(6)}`
            }
            return unit ? `${short(v, d)} ${unit}` : short(v, d)
    }
}
const numberFormats = new Map<string, Intl.NumberFormat>()
function nf(min: number, max: number): Intl.NumberFormat {
    const key = `${min}|${max}`
    let f = numberFormats.get(key)
    if (!f) {
        numberFormats.set(
            key,
            (f = new Intl.NumberFormat(undefined, { minimumFractionDigits: min, maximumFractionDigits: max }))
        )
    }
    return f
}
const dateFormats = new Map<string, Intl.DateTimeFormat>()
export function dtf(kind: string, tz: string | undefined, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
    const key = `${kind}|${tz ?? ''}`
    let f = dateFormats.get(key)
    if (!f) {
        dateFormats.set(key, (f = new Intl.DateTimeFormat(undefined, { ...opts, timeZone: tz })))
    }
    return f
}
export const dateTime = (ms: number, tz?: string): string =>
    dtf('datetime', tz, {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
    }).format(ms)

function full(v: number, d?: number): string {
    return d === undefined ? nf(0, Math.abs(v) < 100 ? 2 : 0).format(v) : nf(d, d).format(v)
}
const sign = (v: number): '' | '-' => (v < 0 ? '-' : '')
function trim(x: number, d: number | undefined, dflt: number): string {
    return nf(d ?? 0, d ?? dflt).format(x)
}
export function short(v: number, d?: number): string {
    let i = 0
    let x = Math.abs(v)
    while (x >= 1000 && i < SI.length - 1) {
        x /= 1000
        i++
    }
    return `${sign(v)}${trim(x, d, i ? 1 : x < 10 ? 2 : 0)}${SI[i]}`
}
function duration(ms: number, d?: number): string {
    const a = Math.abs(ms)
    if (a < 1) {
        return `${trim(ms * 1000, d, 0)} µs`
    }
    if (a < 1000) {
        return `${trim(ms, d, 1)} ms`
    }
    if (a < 60_000) {
        return `${trim(ms / 1000, d, 2)} s`
    }
    if (a < 3_600_000) {
        return `${trim(ms / 60_000, d, 1)} min`
    }
    if (a < 86_400_000) {
        return `${trim(ms / 3_600_000, d, 1)} h`
    }
    return `${trim(ms / 86_400_000, d, 1)} d`
}

export function relativeTime(iso: string): string {
    const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
    if (s < 60) {
        return `${s}s ago`
    }
    if (s < 3600) {
        return `${Math.floor(s / 60)}m ago`
    }
    if (s < 86400) {
        return `${Math.floor(s / 3600)}h ago`
    }
    return `${Math.floor(s / 86400)}d ago`
}
