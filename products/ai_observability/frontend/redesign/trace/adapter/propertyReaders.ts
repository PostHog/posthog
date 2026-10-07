export function readString(value: unknown): string | null {
    return typeof value === 'string' && value !== '' ? value : null
}

export function readNumber(value: unknown): number | null {
    if (typeof value === 'string' && value.trim() === '') {
        return null
    }
    const parsed = typeof value === 'string' ? Number(value) : value
    return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null
}
