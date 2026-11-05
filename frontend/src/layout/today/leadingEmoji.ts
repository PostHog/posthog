const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

export function leadingEmoji(name: string): string | null {
    const [first] = graphemes.segment(name)
    return first && /\p{Extended_Pictographic}/u.test(first.segment) ? first.segment : null
}

export function withoutLeadingEmoji(name: string): string {
    const emoji = leadingEmoji(name)
    return (emoji && name.slice(emoji.length).trimStart()) || name
}
