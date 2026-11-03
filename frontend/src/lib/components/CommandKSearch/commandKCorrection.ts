export interface SearchCorrection {
    from: string
    to: string
}

const QWERTY = "qwertyuiop[]asdfghjkl;'zxcvbnm,./"

// Each layout lists, in QWERTY key order, the letter that key types.
const LAYOUTS = ['йцукенгшщзхъфывапролджэячсмитьбю.', "/'קראטוןםפ][שדגכעיחלךף,זסבהנמצתץ."]

const LATIN = /[a-z]/i
const LAYOUT_LETTER = /[\u0400-\u04ff\u0590-\u05ff]/

function convertKeyboardLayout(text: string): string | null {
    if (LATIN.test(text) || !LAYOUT_LETTER.test(text)) {
        return null
    }
    let converted = ''
    let changed = false
    for (const char of text.toLowerCase()) {
        const layout = LAYOUTS.find((keys) => keys.includes(char))
        converted += layout ? QWERTY[layout.indexOf(char)] : char
        changed ||= !!layout
    }
    return changed && LATIN.test(converted) ? converted : null
}

/** The search to try when the typed text finds nothing: English letters for a wrong keyboard layout, or words split on underscores. */
export function correctedSearch(text: string): string | null {
    const converted = convertKeyboardLayout(text)
    if (converted) {
        return converted
    }
    const split = text.replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
    return split !== text && split ? split : null
}
