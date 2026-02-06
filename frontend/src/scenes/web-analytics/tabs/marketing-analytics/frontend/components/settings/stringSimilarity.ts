export function levenshteinDistance(a: string, b: string): number {
    const matrix: number[][] = []

    for (let i = 0; i <= a.length; i++) {
        matrix[i] = [i]
    }
    for (let j = 0; j <= b.length; j++) {
        matrix[0][j] = j
    }

    for (let i = 1; i <= a.length; i++) {
        for (let j = 1; j <= b.length; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1
            matrix[i][j] = Math.min(matrix[i - 1][j] + 1, matrix[i][j - 1] + 1, matrix[i - 1][j - 1] + cost)
        }
    }

    return matrix[a.length][b.length]
}

export function similarityScore(a: string, b: string): number {
    const normA = a.toLowerCase().trim()
    const normB = b.toLowerCase().trim()

    if (normA === normB) {
        return 1
    }
    if (normA.length === 0 || normB.length === 0) {
        return 0
    }

    const maxLen = Math.max(normA.length, normB.length)
    const distance = levenshteinDistance(normA, normB)
    const base = 1 - distance / maxLen

    // Bonus if one contains the other
    const bonus = normA.includes(normB) || normB.includes(normA) ? 0.2 : 0

    return Math.min(1, base + bonus)
}

export interface CampaignSuggestion {
    name: string
    id: string
    score: number
    matchedBy: 'name' | 'id'
}

export function findCampaignSuggestions(
    input: string,
    campaigns: Array<{ name: string; id: string }>,
    topN: number = 3
): CampaignSuggestion[] {
    if (!input.trim() || campaigns.length === 0) {
        return []
    }

    return campaigns
        .map((c) => {
            const nameScore = similarityScore(input, c.name)
            const idScore = similarityScore(input, c.id)
            return nameScore >= idScore
                ? { ...c, score: nameScore, matchedBy: 'name' as const }
                : { ...c, score: idScore, matchedBy: 'id' as const }
        })
        .sort((a, b) => b.score - a.score)
        .slice(0, topN)
}
