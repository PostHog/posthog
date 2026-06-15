import { RE2JS } from 're2js'

export const isValidRegexp = (regex: string): boolean => {
    try {
        new RegExp(regex)
        return true
    } catch {
        return false
    }
}

export const isValidRE2 = (regex: string): boolean => {
    try {
        RE2JS.compile(regex)
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

export const RE2_DOCS_LINK = 'https://github.com/google/re2/wiki/Syntax'

const HELP_TEXT: Record<string, string> = {
    lookahead: 'Lookahead and lookbehind assertions ((?=test), (?!test), (?<=test), (?<!test)) are not supported.',
    atomicGroup: 'Atomic groups ((?>test)) are not supported.',
    conditional: 'Conditional expressions ((?(1)yes|no)) are not supported.',
    backreference: 'Backreferences (\\1, \\2, etc.) are not supported. Try using alternation or repetition instead.',
    possessive: 'Possessive quantifiers (*+, ++, ?+) are not supported. Use regular quantifiers (*, +, ?) instead.',
    unclosed: 'Check that all brackets and parentheses are properly closed.',
}

function getRE2ErrorContext(re2Error: string, pattern: string): string {
    if (re2Error.includes('invalid or unsupported Perl syntax')) {
        if (re2Error.includes('(?=') || re2Error.includes('(?!')) {
            return HELP_TEXT.lookahead
        }
        if (re2Error.includes('(?>')) {
            return HELP_TEXT.atomicGroup
        }
        if (re2Error.includes('(?(')) {
            return HELP_TEXT.conditional
        }
    }

    if (re2Error.includes('invalid escape sequence') && /\\[1-9]/.test(pattern)) {
        return HELP_TEXT.backreference
    }

    if (re2Error.includes('invalid nested repetition') && /[*+?]\+|{\d+,?\d*}\+/.test(pattern)) {
        return HELP_TEXT.possessive
    }

    if (re2Error.includes('missing closing')) {
        return HELP_TEXT.unclosed
    }

    return ''
}

export function formatRE2Error(error: Error, pattern: string): string {
    const re2Error = String(error.message || error)
    const helpfulContext = getRE2ErrorContext(re2Error, pattern)
    return helpfulContext || re2Error
}
