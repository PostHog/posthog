const PREFIX = 'today-jev:'

function hash(text: string): string {
    let value = 5381
    for (let index = 0; index < text.length; index++) {
        value = ((value << 5) + value + text.charCodeAt(index)) | 0
    }
    return (value >>> 0).toString(36)
}

export function jevCacheKey(kind: string, ...parts: string[]): string {
    return `${PREFIX}${kind}:${hash(parts.join('\u0000'))}`
}

export function readJevCache<T>(key: string): T | undefined {
    try {
        const raw = localStorage.getItem(key)
        return raw === null ? undefined : (JSON.parse(raw) as T)
    } catch {
        return undefined
    }
}

export function writeJevCache(key: string, value: unknown): void {
    try {
        localStorage.setItem(key, JSON.stringify(value))
    } catch {
        return
    }
}
