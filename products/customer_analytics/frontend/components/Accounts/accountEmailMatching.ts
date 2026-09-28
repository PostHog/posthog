export function cleanEmails(values: string[]): string[] {
    return Array.from(new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean)))
}

export function cleanDomains(values: string[]): string[] {
    return cleanEmails(values.map((value) => value.replace(/^@/, '')))
}
