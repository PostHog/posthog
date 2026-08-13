const GENERATED_NAME_MAX_LENGTH = 80

export function getGenUIName(prompt: string): string {
    const normalized = prompt.trim().replace(/\s+/g, ' ')
    if (!normalized) {
        return 'Custom visualization'
    }
    if (normalized.length <= GENERATED_NAME_MAX_LENGTH) {
        return normalized
    }
    return `${normalized.slice(0, GENERATED_NAME_MAX_LENGTH - 3).trimEnd()}...`
}
