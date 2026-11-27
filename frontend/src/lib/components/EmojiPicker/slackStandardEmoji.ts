export interface SlackStandardEmoji {
    /** The name Slack uses for this emoji, such as `white_check_mark`. */
    name: string
    /** Every name Slack accepts for this emoji. The first one is `name`. */
    names: string[]
    /** The emoji as text, for showing it without an image. */
    character: string
}

let loading: Promise<SlackStandardEmoji[]> | null = null

function characterFromHexcode(hexcode: string): string {
    const codePoints = hexcode.split('-').map((part) => parseInt(part, 16))
    // A lone symbol from the older Unicode blocks, such as U+26A0 for `warning`, renders as text without the
    // emoji variation selector.
    if (codePoints.length === 1 && codePoints[0] < 0x1f000) {
        codePoints.push(0xfe0f)
    }
    return String.fromCodePoint(...codePoints)
}

/** Slack's standard emoji names, from the `iamcal` shortcode set that Slack uses. Loaded once, on first use. */
export function loadSlackStandardEmoji(): Promise<SlackStandardEmoji[]> {
    loading ??= import('emojibase-data/en/shortcodes/iamcal.json')
        .then(({ default: shortcodes }) =>
            Object.entries(shortcodes).map(([hexcode, value]) => {
                const names = Array.isArray(value) ? value : [value]
                return { name: names[0], names, character: characterFromHexcode(hexcode) }
            })
        )
        .catch((error) => {
            // A failed chunk load is not cached, so the next caller tries again.
            loading = null
            throw error
        })
    return loading
}
