export function normalizeAxisLabel(label: string | null | undefined): string | undefined {
    const trimmed = label?.trim()
    return trimmed ? trimmed : undefined
}
