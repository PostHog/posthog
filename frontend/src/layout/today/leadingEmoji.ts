let segmenter: Intl.Segmenter | null | undefined

/**
 * The grapheme segmenter, built on first use and only if the browser has it. At module scope a
 * browser without `Intl.Segmenter`, such as Firefox before 125, fails the import and takes the whole
 * top bar down.
 */
function graphemeSegmenter(): Intl.Segmenter | null {
    if (segmenter === undefined) {
        segmenter =
            typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null
    }
    return segmenter
}

/**
 * A leading emoji for a browser with no segmenter: one pictograph, then the skin tones, the
 * variation selectors and the zero-width joins that extend it into one character.
 */
const LEADING_EMOJI = /^\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|️|‍\p{Extended_Pictographic})*/u

export function leadingEmoji(name: string): string | null {
    const segments = graphemeSegmenter()
    if (!segments) {
        return name.match(LEADING_EMOJI)?.[0] ?? null
    }
    const [first] = segments.segment(name)
    return first && /\p{Extended_Pictographic}/u.test(first.segment) ? first.segment : null
}

export function withoutLeadingEmoji(name: string): string {
    const emoji = leadingEmoji(name)
    return (emoji && name.slice(emoji.length).trimStart()) || name
}
