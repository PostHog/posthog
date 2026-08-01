// Common personal email domains people mistype. Deliberately short: this is a nudge for
// obvious typos, not an exhaustive provider list.
const COMMON_EMAIL_DOMAINS = [
    'gmail.com',
    'yahoo.com',
    'hotmail.com',
    'outlook.com',
    'icloud.com',
    'aol.com',
    'protonmail.com',
    'live.com',
    'msn.com',
]

// Covers the vast majority of real addresses, so a domain ending in anything else (a
// stray trailing character, a typo'd letter) is worth flagging regardless of company name.
const COMMON_TLDS = ['com', 'net', 'org', 'io', 'co', 'dev', 'app', 'ai', 'edu', 'gov', 'biz', 'info']

// Damerau-Levenshtein (with adjacent transposition) rather than plain Levenshtein, since
// swapped-letter typos ("cmo" for "com") are common and would otherwise cost 2 edits instead of 1.
function editDistance(a: string, b: string): number {
    const rows = a.length + 1
    const cols = b.length + 1
    const distances: number[][] = Array.from({ length: rows }, () => new Array(cols).fill(0))

    for (let i = 0; i < rows; i++) {
        distances[i][0] = i
    }
    for (let j = 0; j < cols; j++) {
        distances[0][j] = j
    }

    for (let i = 1; i < rows; i++) {
        for (let j = 1; j < cols; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1
            distances[i][j] = Math.min(distances[i - 1][j] + 1, distances[i][j - 1] + 1, distances[i - 1][j - 1] + cost)

            if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
                distances[i][j] = Math.min(distances[i][j], distances[i - 2][j - 2] + 1)
            }
        }
    }

    return distances[rows - 1][cols - 1]
}

function suggestKnownProviderTypo(domain: string): string | null {
    for (const candidate of COMMON_EMAIL_DOMAINS) {
        if (domain === candidate) {
            return null
        }

        const distance = editDistance(domain, candidate)
        const maxDistance = candidate.length > 8 ? 2 : 1

        if (distance > 0 && distance <= maxDistance) {
            return candidate
        }
    }

    return null
}

// Catches typos in the TLD of any domain (company domains included), e.g. "example.com5"
// or "example.cmo", without needing to know the domain name itself.
function suggestTldTypo(domain: string): string | null {
    const lastDotIndex = domain.lastIndexOf('.')
    if (lastDotIndex === -1) {
        return null
    }

    const namePart = domain.slice(0, lastDotIndex)
    const tld = domain.slice(lastDotIndex + 1)

    if (!namePart || COMMON_TLDS.includes(tld)) {
        return null
    }

    // A domain ending in a known TLD plus junk (e.g. "com5") is an unambiguous typo, so it
    // always wins over a same-distance misspelling of some other TLD.
    for (const knownTld of COMMON_TLDS) {
        if (tld.length > knownTld.length && tld.startsWith(knownTld) && tld.length - knownTld.length <= 2) {
            return `${namePart}.${knownTld}`
        }
    }

    let bestMatch: string | null = null
    let bestDistance = Infinity

    for (const knownTld of COMMON_TLDS) {
        if (tld.length > knownTld.length + 1) {
            continue
        }

        const distance = editDistance(tld, knownTld)
        if (distance <= 1 && distance < bestDistance) {
            bestMatch = knownTld
            bestDistance = distance
        }
    }

    return bestMatch ? `${namePart}.${bestMatch}` : null
}

/**
 * Suggests a corrected email domain when the address looks like a near-miss typo — either
 * of a common personal provider (e.g. "user@gmial.com" -> "user@gmail.com") or of the TLD on
 * any domain (e.g. "user@example.com5" -> "user@example.com"). Returns null when the domain
 * already looks fine or is too different to guess confidently.
 */
export function suggestEmailDomain(email: string): string | null {
    const atIndex = email.lastIndexOf('@')
    if (atIndex === -1 || atIndex === email.length - 1) {
        return null
    }

    const localPart = email.slice(0, atIndex)
    const domain = email.slice(atIndex + 1).toLowerCase()

    if (!domain) {
        return null
    }

    const suggestedDomain = suggestKnownProviderTypo(domain) ?? suggestTldTypo(domain)

    return suggestedDomain ? `${localPart}@${suggestedDomain}` : null
}
