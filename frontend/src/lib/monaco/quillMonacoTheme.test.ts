import {
    QUILL_MONACO_THEME_DARK,
    QUILL_MONACO_THEME_LIGHT,
    QuillColorResolver,
    QuillThemeToken,
    buildQuillMonacoTheme,
    compositeOver,
    defineQuillMonacoTheme,
} from './quillMonacoTheme'

const LIGHT: Partial<Record<QuillThemeToken, string>> = {
    card: '#ffffff',
    foreground: '#101010',
    'muted-foreground': '#555555',
    'subtle-foreground': '#000000cc',
    border: '#dddddd',
    'fill-hover': '#1010100a',
    'fill-selected': '#1010100f',
    primary: '#f54e00',
    'completed-foreground': '#6b3fd4',
    'success-foreground': '#1f7a3a',
    'warning-foreground': '#8a5a00',
    'destructive-foreground': '#c0262d',
}

const DARK: Partial<Record<QuillThemeToken, string>> = {
    ...LIGHT,
    card: '#1a1c22',
    foreground: '#f4f4f6',
    'subtle-foreground': '#ffffff80',
    primary: '#f7a501',
}

const resolverFor =
    (values: Partial<Record<QuillThemeToken, string>>): QuillColorResolver =>
    (token) =>
        values[token] ?? null

const ruleFor = (theme: ReturnType<typeof buildQuillMonacoTheme>, token: string): Record<string, any> | undefined =>
    theme.rules.find((rule) => rule.token === token)

describe('quillMonacoTheme', () => {
    test.each([
        ['opaque passes through', '#123456', '#ffffff', '#123456'],
        ['half alpha over white', '#00000080', '#ffffff', '#7f7f7f'],
        ['transparent yields background', '#ff000000', '#1a1c22', '#1a1c22'],
        ['invalid input', 'oklch(0.5 0 0)', '#ffffff', null],
    ])('compositeOver: %s', (_, fg, bg, expected) => {
        expect(compositeOver(fg, bg)).toEqual(expected)
    })

    it('maps tokens to rules with valid opaque hex and the right font styles', () => {
        const theme = buildQuillMonacoTheme(resolverFor(LIGHT), false)

        expect(theme.base).toEqual('vs')
        expect(ruleFor(theme, 'keyword')).toEqual({ token: 'keyword', foreground: 'f54e00', fontStyle: 'bold' })
        expect(ruleFor(theme, 'predefined')?.foreground).toEqual('6b3fd4')
        expect(ruleFor(theme, 'string')?.foreground).toEqual('1f7a3a')
        expect(ruleFor(theme, 'number')?.foreground).toEqual('8a5a00')
        // 80% black over white.
        expect(ruleFor(theme, 'comment')).toEqual({ token: 'comment', foreground: '333333', fontStyle: 'italic' })
        for (const rule of theme.rules) {
            expect(rule.foreground).toMatch(/^[0-9a-f]{6}$/)
        }
    })

    it('keeps alpha on editor colors and leaves unresolved tokens out', () => {
        const theme = buildQuillMonacoTheme(resolverFor(LIGHT), false)

        expect(theme.colors).toMatchObject({
            'editor.background': '#ffffff',
            'editor.selectionBackground': '#1010100f',
            'editor.lineHighlightBackground': '#1010100a',
            'editorLineNumber.foreground': '#000000cc',
            'editorError.foreground': '#c0262d',
        })
        expect(theme.colors).not.toHaveProperty('focusBorder')
        for (const color of Object.values(theme.colors)) {
            expect(color).toMatch(/^#[0-9a-f]{6}([0-9a-f]{2})?$/)
        }
        expect(ruleFor(theme, 'type')).toBeUndefined()
    })

    it('builds dark from the dark token values', () => {
        const light = buildQuillMonacoTheme(resolverFor(LIGHT), false)
        const dark = buildQuillMonacoTheme(resolverFor(DARK), true)

        expect(dark.base).toEqual('vs-dark')
        expect(dark.colors['editor.background']).toEqual('#1a1c22')
        expect(ruleFor(dark, 'keyword')?.foreground).toEqual('f7a501')
        expect(ruleFor(dark, 'comment')?.foreground).not.toEqual(ruleFor(light, 'comment')?.foreground)
    })

    test.each([
        [false, QUILL_MONACO_THEME_LIGHT, 'vs'],
        [true, QUILL_MONACO_THEME_DARK, 'vs-dark'],
    ])('defineQuillMonacoTheme(isDark=%s) defines and returns %s', (isDark, expectedName, expectedBase) => {
        const defined: Record<string, any> = {}
        const monaco = { editor: { defineTheme: (name: string, data: any) => (defined[name] = data) } }

        const name = defineQuillMonacoTheme(monaco, document.createElement('div'), isDark)

        expect(name).toEqual(expectedName)
        expect(defined[expectedName].base).toEqual(expectedBase)
    })
})
