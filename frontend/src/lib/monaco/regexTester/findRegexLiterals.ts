/** A string literal in a query that is used as a regex pattern. */
export interface RegexLiteral {
    /** Offset of the first character inside the opening quote. */
    start: number
    /** Offset of the closing quote. */
    end: number
    /** The literal's value, with the escapes SQL itself consumes already resolved. */
    pattern: string
}

/**
 * Zero-based argument position each function treats as a regex pattern. Names are lowercased
 * because HogQL resolves function names case-insensitively.
 */
const REGEX_ARGUMENT_INDEX: Record<string, number> = {
    match: 1,
    multimatchany: 1,
    multimatchanyindex: 1,
    multimatchallindices: 1,
    extract: 1,
    extractall: 1,
    extractallgroups: 1,
    extractallgroupshorizontal: 1,
    extractallgroupsvertical: 1,
    countmatches: 1,
    countmatchescaseinsensitive: 1,
    replaceregexpall: 1,
    replaceregexpone: 1,
    splitbyregexp: 0,
}

/** Comparison operators whose right-hand literal is a regex. Longest first so `=~*` beats `=~`. */
const REGEX_OPERATORS = ['=~*', '!~*', '=~', '!~', '~*', '~']

const WORD_CHARACTER = /[A-Za-z0-9_$]/
const WHITESPACE = /\s/

interface Frame {
    /** Lowercased function name, or null for a bare group such as a subquery. */
    name: string | null
    argumentIndex: number
    /** Array literals inherit the regex-ness of the argument they sit in, so every element counts. */
    everyArgumentIsRegex: boolean
}

function frameHoldsRegexArgument(frame: Frame | undefined): boolean {
    if (!frame) {
        return false
    }
    if (frame.everyArgumentIsRegex) {
        return true
    }
    return frame.name !== null && REGEX_ARGUMENT_INDEX[frame.name] === frame.argumentIndex
}

interface ScannedLiteral extends RegexLiteral {
    /** Where scanning resumes, past the closing quote. */
    nextOffset: number
    terminated: boolean
}

function readStringLiteral(text: string, quoteOffset: number): ScannedLiteral {
    const start = quoteOffset + 1
    let pattern = ''
    let offset = start

    while (offset < text.length) {
        const character = text[offset]
        if (character === '\\' && offset + 1 < text.length) {
            const escaped = text[offset + 1]
            // Only the escapes SQL consumes are resolved. Regex escapes (\d, \s, \b …) have to
            // reach the engine with their backslash intact.
            pattern += escaped === '\\' || escaped === "'" ? escaped : character + escaped
            offset += 2
            continue
        }
        if (character === "'") {
            if (text[offset + 1] === "'") {
                pattern += "'"
                offset += 2
                continue
            }
            return { start, end: offset, pattern, nextOffset: offset + 1, terminated: true }
        }
        pattern += character
        offset++
    }

    return { start, end: text.length, pattern, nextOffset: text.length, terminated: false }
}

function skipQuotedIdentifier(text: string, quoteOffset: number): number {
    const quote = text[quoteOffset]
    let offset = quoteOffset + 1
    while (offset < text.length) {
        if (text[offset] === '\\') {
            offset += 2
            continue
        }
        if (text[offset] === quote) {
            return offset + 1
        }
        offset++
    }
    return text.length
}

/**
 * Finds the string literals a HogQL/ClickHouse query hands to a regex engine, either as an
 * argument to a regex function (`match`, `extract`, `replaceRegexpAll`, …) or on the right of a
 * regex operator (`=~`, `!~`, …).
 */
export function findRegexLiterals(text: string): RegexLiteral[] {
    const literals: RegexLiteral[] = []
    const frames: Frame[] = []
    let lastWord: string | null = null
    let afterRegexOperator = false
    let offset = 0

    while (offset < text.length) {
        const character = text[offset]

        if (character === '-' && text[offset + 1] === '-') {
            const newline = text.indexOf('\n', offset)
            offset = newline === -1 ? text.length : newline + 1
            continue
        }
        if (character === '/' && text[offset + 1] === '*') {
            const close = text.indexOf('*/', offset + 2)
            offset = close === -1 ? text.length : close + 2
            continue
        }
        if (WHITESPACE.test(character)) {
            offset++
            continue
        }

        if (character === "'") {
            const literal = readStringLiteral(text, offset)
            if (literal.terminated && (afterRegexOperator || frameHoldsRegexArgument(frames[frames.length - 1]))) {
                literals.push({ start: literal.start, end: literal.end, pattern: literal.pattern })
            }
            afterRegexOperator = false
            lastWord = null
            offset = literal.nextOffset
            continue
        }

        if (character === '"' || character === '`') {
            offset = skipQuotedIdentifier(text, offset)
            afterRegexOperator = false
            lastWord = null
            continue
        }

        if (WORD_CHARACTER.test(character)) {
            let wordEnd = offset
            while (wordEnd < text.length && WORD_CHARACTER.test(text[wordEnd])) {
                wordEnd++
            }
            lastWord = text.slice(offset, wordEnd).toLowerCase()
            afterRegexOperator = false
            offset = wordEnd
            continue
        }

        if (character === '(' || character === '[') {
            frames.push({
                name: character === '(' ? lastWord : null,
                argumentIndex: 0,
                everyArgumentIsRegex: character === '[' && frameHoldsRegexArgument(frames[frames.length - 1]),
            })
            lastWord = null
            afterRegexOperator = false
            offset++
            continue
        }

        if (character === ')' || character === ']') {
            frames.pop()
            lastWord = null
            afterRegexOperator = false
            offset++
            continue
        }

        if (character === ',') {
            const frame = frames[frames.length - 1]
            if (frame) {
                frame.argumentIndex++
            }
            lastWord = null
            afterRegexOperator = false
            offset++
            continue
        }

        const operator = REGEX_OPERATORS.find((candidate) => text.startsWith(candidate, offset))
        if (operator) {
            afterRegexOperator = true
            lastWord = null
            offset += operator.length
            continue
        }

        lastWord = null
        afterRegexOperator = false
        offset++
    }

    return literals
}
