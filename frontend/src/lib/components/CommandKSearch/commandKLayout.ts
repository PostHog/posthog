export interface LayoutCorrection {
    from: string
    to: string
}

const QWERTY = "qwertyuiop[]asdfghjkl;'zxcvbnm,./"

const LAYOUTS = [
    'йцукенгшщзхъфывапролджэячсмитьбю.',
    "/'קראטוןםפ][שדגכעיחלךף,זסבהנמצתץ.",
    'ضصثقفغعهخحجدشسيبلاتنمكطئءؤرىةوزظ',
]

const LATIN = /[a-z]/i

export function convertKeyboardLayout(text: string): string | null {
    if (LATIN.test(text)) {
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
