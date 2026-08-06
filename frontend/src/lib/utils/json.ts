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
// crashes serialization. Only bigints are handled — circular references and other
// unserializable values still throw, same as JSON.stringify. The bigint->string
// conversion is lossy, which is fine here: the result is only used for
// URL encoding and change-detection keys, not to reconstruct the original value.
export function stringifyWithBigInts(value: unknown): string {
    return JSON.stringify(value, (_key, val) => (typeof val === 'bigint' ? val.toString() : val))
}
