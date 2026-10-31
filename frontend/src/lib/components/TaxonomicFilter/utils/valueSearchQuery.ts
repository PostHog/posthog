export function isEmailLikeSearch(query: string): boolean {
    return query.includes('@') || /^[^@\s/:]+\.[a-z][^@\s/:]*$/i.test(query.trim())
}

export function isUrlLikeSearch(query: string): boolean {
    const trimmed = query.trim()
    return (
        !/\s/.test(trimmed) &&
        (trimmed.includes('/') ||
            /^https?:/i.test(trimmed) ||
            /^www\./i.test(trimmed) ||
            /^[^@]+\.[a-z]/i.test(trimmed))
    )
}
