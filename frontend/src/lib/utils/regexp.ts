export const isValidRegexp = (regex: string): boolean => {
    try {
        new RegExp(regex)
        return true
    } catch {
        return false
    }
}

export function isLikelyRegex(url: string): boolean {
    // Common regex special characters that indicate regex pattern
    const regexSpecialChars = /[.*+?^${}()|[\]\\]/

    // Check for common regex anchors
    const hasAnchors = url.startsWith('^') || url.endsWith('$')

    // Check for regex special characters
    const hasSpecialChars = regexSpecialChars.test(url)

    return hasAnchors || hasSpecialChars
}

// Combine both checks if you want to be extra sure
export function isValidRegexPattern(s: string): boolean {
    return isLikelyRegex(s) && isValidRegexp(s)
}
