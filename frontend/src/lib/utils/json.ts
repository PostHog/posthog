export function validateJson(value: string): boolean {
    try {
        JSON.parse(value)
        return true
    } catch {
        return false
    }
}

export function tryJsonParse(value: string, fallback?: any): any {
    try {
        return JSON.parse(value)
    } catch {
        return fallback
    }
}

// Like JSON.stringify, but converts bigints to strings instead of throwing.
// Filter property values can be bigint (PropertyFilterBaseValue), which otherwise
// crashes serialization. The bigint->string conversion is lossy, which is fine
// for the only use cases here: change comparison and URL encoding.
export function safeStringify(value: unknown): string | undefined {
    return JSON.stringify(value, (_key, val) => (typeof val === 'bigint' ? val.toString() : val))
}
