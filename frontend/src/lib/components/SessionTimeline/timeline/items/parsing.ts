export function parseIfJSONString<T>(value: unknown): T | undefined {
    if (value == null) {
        return undefined
    }

    if (typeof value === 'string') {
        try {
            return JSON.parse(value) as T
        } catch {
            return undefined
        }
    }

    return value as T
}

export function parseRecordIfJSONString(value: unknown): Record<string, unknown> {
    const parsed = parseIfJSONString<unknown>(value)

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return {}
    }

    return parsed as Record<string, unknown>
}

export function escapeHogQLString(value: string): string {
    return value.replaceAll('\\', '\\\\').replaceAll("'", "\\'")
}
