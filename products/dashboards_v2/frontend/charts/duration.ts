const UNIT_MS: Record<string, number> = { s: 1e3, m: 6e4, h: 36e5, d: 864e5, w: 6048e5 }

export function parseDuration(text: string): number {
    const match = /^(\d+)([smhdw])$/.exec(text.trim())
    if (!match) {
        throw new Error(`invalid duration "${text}"`)
    }
    return Number(match[1]) * UNIT_MS[match[2]]
}
