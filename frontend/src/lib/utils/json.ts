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
