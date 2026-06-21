import { humanFriendlyNumber } from 'lib/utils/numbers'

export function toSentenceCase(str: string): string {
    return str.replace(/\b\w/g, (c) => c.toUpperCase())
}

export function splitKebabCase(string: string): string {
    return string.replace(/-/g, ' ')
}

export function capitalizeFirstLetter(string: string): string {
    return string.charAt(0).toUpperCase() + string.slice(1)
}

export function lowercaseFirstLetter(string: string): string {
    return string.charAt(0).toLowerCase() + string.slice(1)
}

export function getOrdinalSuffix(num: number): string {
    const j = num % 10
    const k = num % 100
    if (j === 1 && k !== 11) {
        return 'st'
    }
    if (j === 2 && k !== 12) {
        return 'nd'
    }
    if (j === 3 && k !== 13) {
        return 'rd'
    }
    return 'th'
}

export function fullName(props?: { first_name?: string; last_name?: string }): string {
    if (!props) {
        return 'Unknown User'
    }
    return `${props.first_name || ''} ${props.last_name || ''}`.trim()
}

// trimBothEnds=false is useful when the input is slugified as the user is typing to allow them hitting space and continue typing
export function slugify(
    text: string,
    { trimBothEnds = true, lowercase = true }: { trimBothEnds?: boolean; lowercase?: boolean } = {}
): string {
    let result = text.toString()
    if (lowercase) {
        result = result.toLowerCase()
    }
    return result
        .normalize('NFD') // The normalize() method returns the Unicode Normalization Form of a given string.
        [trimBothEnds ? 'trim' : 'trimStart']()
        .replace(/\s+/g, '-') // Replace spaces with -
        .replace(/[^\w-]+/g, '') // Remove all non-word chars
        .replace(/--+/g, '-')
}

export function truncate(str: string, maxLength: number): string {
    return str.length > maxLength ? str.slice(0, maxLength - 1) + '...' : str
}

/** Convert camelCase, PascalCase or snake_case to Sentence case or Title Case. */
export function identifierToHuman(identifier: string | number, caseType: 'sentence' | 'title' = 'sentence'): string {
    const words: string[] = []
    let currentWord: string = ''
    String(identifier)
        .trim()
        .split('')
        .forEach((character) => {
            if (character === '_' || character === '-' || character === '/') {
                if (currentWord) {
                    words.push(currentWord)
                }
                currentWord = ''
            } else if (
                character === character.toLowerCase() &&
                (!'0123456789'.includes(character) ||
                    (currentWord && '0123456789'.includes(currentWord[currentWord.length - 1])))
            ) {
                currentWord += character
            } else {
                if (currentWord) {
                    words.push(currentWord)
                }
                currentWord = character.toLowerCase()
            }
        })
    if (currentWord) {
        words.push(currentWord)
    }
    return capitalizeFirstLetter(
        words.map((word) => (caseType === 'sentence' ? word : capitalizeFirstLetter(word))).join(' ')
    )
}

export function hashCodeForString(s: string): number {
    /* Hash function that returns a number for a given string. Useful for using the same colors for tags or avatars.
    Forked from https://github.com/segmentio/evergreen/
    */
    let hash = 0
    if (s.trim().length === 0) {
        return hash
    }
    for (let i = 0; i < s.length; i++) {
        const char = s.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash &= hash // Convert to 32bit integer
    }
    return Math.abs(hash)
}

/** Truncates a string (`input`) in the middle. `maxLength` represents the desired maximum length of the output. */
export function midEllipsis(input: string, maxLength: number): string {
    if (input.length <= maxLength) {
        return input
    }

    const middle = Math.ceil(input.length / 2)
    const excessLeft = Math.ceil((input.length - maxLength) / 2)
    const excessRight = Math.ceil((input.length - maxLength + 1) / 2)
    return `${input.slice(0, middle - excessLeft)}…${input.slice(middle + excessRight)}`
}

export function pluralize(count: number, singular: string, plural?: string, includeNumber: boolean = true): string {
    if (!plural) {
        plural = singular + 's'
    }
    const form = count === 1 ? singular : plural
    return includeNumber ? `${humanFriendlyNumber(count)} ${form}` : form
}

const WORD_PLURALIZATION_RULES = [
    [/s?$/i, 's'],
    [/([^aeiou]ese)$/i, '$1'],
    [/(ax|test)is$/i, '$1es'],
    [/(alias|[^aou]us|t[lm]as|gas|ris)$/i, '$1es'],
    [/(e[mn]u)s?$/i, '$1s'],
    [/([^l]ias|[aeiou]las|[ejzr]as|[iu]am)$/i, '$1'],
    [/(alumn|syllab|vir|radi|nucle|fung|cact|stimul|termin|bacill|foc|uter|loc|strat)(?:us|i)$/i, '$1i'],
    [/(alumn|alg|vertebr)(?:a|ae)$/i, '$1ae'],
    [/(seraph|cherub)(?:im)?$/i, '$1im'],
    [/(her|at|gr)o$/i, '$1oes'],
    [
        /(agend|addend|millenni|dat|extrem|bacteri|desiderat|strat|candelabr|errat|ov|symposi|curricul|automat|quor)(?:a|um)$/i,
        '$1a',
    ],
    [/(apheli|hyperbat|periheli|asyndet|noumen|phenomen|criteri|organ|prolegomen|hedr|automat)(?:a|on)$/i, '$1a'],
    [/sis$/i, 'ses'],
    [/(?:(kni|wi|li)fe|(ar|l|ea|eo|oa|hoo)f)$/i, '$1$2ves'],
    [/([^aeiouy]|qu)y$/i, '$1ies'],
    [/([^ch][ieo][ln])ey$/i, '$1ies'],
    [/(x|ch|ss|sh|zz)$/i, '$1es'],
    [/(matr|cod|mur|sil|vert|ind|append)(?:ix|ex)$/i, '$1ices'],
    [/\b((?:tit)?m|l)(?:ice|ouse)$/i, '$1ice'],
    [/(pe)(?:rson|ople)$/i, '$1ople'],
    [/(child)(?:ren)?$/i, '$1ren'],
    [/eaux$/i, '$0'],
    [/m[ae]n$/i, 'men'],
] as [RegExp, string][]

export function wordPluralize(word: string): string {
    if (!word) {
        return word ?? ''
    }

    let len = WORD_PLURALIZATION_RULES.length

    // Iterate over the sanitization rules and use the first one to match.
    while (len--) {
        const [regex, replacement] = WORD_PLURALIZATION_RULES[len]
        if (regex.test(word)) {
            return word.replace(regex, replacement)
        }
    }

    return word
}

export const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')

export function endWithPunctation(text?: string | null): string {
    let trimmedText = text?.trim()
    if (!trimmedText) {
        return ''
    }
    if (!/[.!?]$/.test(trimmedText)) {
        trimmedText += '.'
    }
    return trimmedText
}

/** Join array of string into a list ("a, b, and c"). Uses the Oxford comma, but only if there are at least 3 items. */
export function humanList(arr: readonly string[]): string {
    return arr.length > 2 ? arr.slice(0, -1).join(', ') + ', and ' + arr.at(-1) : arr.join(' and ')
}

export function toString(input?: any): string {
    return input?.toString() || ''
}

export function ensureStringIsNotBlank(s?: string | null): string | null {
    return typeof s === 'string' && s.trim() !== '' ? s : null
}

export function isMultiSeriesFormula(formula?: string | null): boolean {
    if (!formula) {
        return false
    }
    const count = (formula.match(/[a-zA-Z]/g) || []).length
    return count > 1
}
