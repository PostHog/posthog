/** What one run of a suggested evaluation reads, in the words a person uses for it. */
export const UNITS: Record<string, [string, string]> = {
    generation: ['generation', 'generations'],
    trace: ['trace', 'traces'],
    session: ['conversation', 'conversations'],
}

export function unitNoun(target: string | undefined, count: number): string {
    const [singular, plural] = UNITS[target ?? 'trace'] ?? UNITS.trace
    return count === 1 ? singular : plural
}
