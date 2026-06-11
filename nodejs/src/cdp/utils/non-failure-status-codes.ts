const WILDCARD_PATTERN = /^([4-5])xx$/i

export function isNonFailureStatus(
    status: number | undefined,
    config: Array<number | string> | null | undefined
): boolean {
    if (typeof status !== 'number' || !Array.isArray(config) || config.length === 0) {
        return false
    }

    for (const entry of config) {
        if (typeof entry === 'number' && Number.isInteger(entry) && entry === status) {
            return true
        }
        if (typeof entry === 'string') {
            const match = WILDCARD_PATTERN.exec(entry)
            if (match) {
                const rangeStart = parseInt(match[1], 10) * 100
                if (status >= rangeStart && status < rangeStart + 100) {
                    return true
                }
            }
        }
    }

    return false
}
