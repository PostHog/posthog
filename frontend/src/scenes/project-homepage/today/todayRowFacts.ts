const PULL_REQUEST_FACTS: Record<string, string> = {
    draft: 'Fix in progress',
    open: 'Fix ready for review',
    merged: 'Fix merged',
}

export function pullRequestFact(state: string | null | undefined): string | null {
    return state ? (PULL_REQUEST_FACTS[state] ?? null) : null
}

export function rowFacts(parts: (string | null | undefined)[]): string[] {
    const shown: string[] = []
    for (const part of parts) {
        if (part && !shown.some((earlier) => earlier.toLowerCase().includes(part.toLowerCase()))) {
            shown.push(part)
        }
    }
    return shown
}
