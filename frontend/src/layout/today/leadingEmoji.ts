let segmenter: Intl.Segmenter | null | undefined

// Firefox before 125 has no `Intl.Segmenter`. At module scope the constructor throws there and fails
// the import, which takes the top bar down, so build it on first use and only if it exists.
function graphemeSegmenter(): Intl.Segmenter | null {
    if (segmenter === undefined) {
        segmenter =
            typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null
    }
    return segmenter
}

// A leading emoji for a browser with no segmenter: one pictograph, then the skin tones, variation
// selectors, flag tags and zero-width joins that extend it into one character.
const LEADING_EMOJI =
    /^\p{Extended_Pictographic}(?:\p{Emoji_Modifier}|\u{FE0F}|[\u{E0020}-\u{E007F}]|\u{200D}\p{Extended_Pictographic})*/u

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
