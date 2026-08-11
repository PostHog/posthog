import { languages } from 'monaco-editor'

import { TemplateLanguage, templateAutocompleteProvider } from 'lib/monaco/templateAutocompleteProvider'

import { HogLanguage } from '~/queries/schema/schema-general'

// Jest resolves monaco-editor to its type declarations, which leaves CompletionItemKind with no
// runtime value. Restate the members the provider uses, keeping monaco's own numbering.
jest.mock('monaco-editor', () => ({
    languages: { CompletionItemKind: { Method: 0, Function: 1, Field: 3, Variable: 4 } },
}))

const GLOBALS: Record<string, unknown> = {
    event: { event: '$pageview', properties: { $browser: 'Chrome' } },
    person: { distinct_id: 'abc123', properties: { email: 'marius@example.com', name: 'Marius' } },
}

interface SuggestOptions {
    language: TemplateLanguage
    /** Text of the single-line editor up to the cursor. */
    before: string
    after?: string
    globals?: Record<string, unknown>
}

function suggest(options: SuggestOptions): languages.CompletionItem[] {
    const { language, before, after = '' } = options
    const globals = 'globals' in options ? options.globals : GLOBALS
    const cursorColumn = before.length + 1
    const word = /[A-Za-z0-9_$]*$/.exec(before)![0]
    const model = {
        codeEditorLogic: { isMounted: () => true, props: { globals } },
        getValue: () => before + after,
        getOffsetAt: ({ column }: { column: number }) => column - 1,
        getWordUntilPosition: () => ({
            word,
            startColumn: cursorColumn - word.length,
            endColumn: cursorColumn,
        }),
    }
    const result = templateAutocompleteProvider(language).provideCompletionItems?.(
        model as any,
        { lineNumber: 1, column: cursorColumn } as any,
        {} as any,
        {} as any
    )
    return (result as languages.CompletionList).suggestions
}

function labels(suggestions: languages.CompletionItem[]): string[] {
    return suggestions.map((item) => (typeof item.label === 'string' ? item.label : item.label.label))
}

describe('templateAutocompleteProvider', () => {
    test.each([
        ['after a top-level global', '{person.', ['distinct_id', 'properties']],
        ['after a nested global', '{person.properties.', ['email', 'name']],
        ['while typing a member', '{person.properties.em', ['email', 'name']],
        ['with the cursor in the middle of a chain', '{person.prop', ['distinct_id', 'properties']],
        ['on a leaf that is not an object', '{person.properties.email.', []],
        ['on a global that does not exist', '{unknown.', []],
    ])('walks the chain into globals %s', (_name, before, expected) => {
        const suggestions = suggest({ language: HogLanguage.hogTemplate, before, after: '}' })

        expect(labels(suggestions)).toEqual(expected)
        expect(suggestions.every((item) => item.kind === languages.CompletionItemKind.Field)).toBe(true)
    })

    test('suggests globals and Hog functions at the top level of a Hog template', () => {
        const suggestions = suggest({ language: HogLanguage.hogTemplate, before: 'Hi {', after: '}' })

        expect(suggestions).toContainEqual(
            expect.objectContaining({
                label: { label: 'person', detail: 'Object' },
                kind: languages.CompletionItemKind.Variable,
                sortText: '1-person',
            })
        )
        expect(suggestions).toContainEqual(
            expect.objectContaining({
                label: 'concat',
                insertText: 'concat()',
                kind: languages.CompletionItemKind.Function,
                command: { id: 'cursorLeft', title: 'Move cursor left' },
            })
        )
    })

    test('suggests Hog functions when no globals are set', () => {
        const suggestions = suggest({ language: HogLanguage.hogTemplate, before: '{', globals: undefined })

        expect(labels(suggestions)).toContain('concat')
        expect(suggestions.every((item) => item.kind === languages.CompletionItemKind.Function)).toBe(true)
    })

    test.each<[TemplateLanguage, string]>([
        [HogLanguage.hogTemplate, 'Hi there '],
        [HogLanguage.hogTemplate, 'Hi {person.properties.name} '],
        [HogLanguage.liquid, 'Hi there '],
        [HogLanguage.liquid, 'Hi {{ person.properties.name }} '],
    ])('suggests nothing outside a %s expression: %p', (language, before) => {
        expect(suggest({ language, before })).toEqual([])
    })

    test.each([
        ['output', '{{ '],
        ['tag', '{% if '],
    ])('suggests globals inside a Liquid %s expression', (_name, before) => {
        const suggestions = suggest({ language: HogLanguage.liquid, before })

        expect(labels(suggestions)).toEqual(['event', 'person'])
    })

    test.each([
        ['right after the pipe', '{{ person.properties.email | '],
        ['while typing the filter name', '{{ person.properties.email | up'],
    ])('suggests Liquid filters %s', (_name, before) => {
        const suggestions = suggest({ language: HogLanguage.liquid, before })

        expect(labels(suggestions)).toContain('upcase')
        // Hog's standard library is not available in Liquid, so it must never be offered there.
        expect(labels(suggestions)).not.toContain('concat')
    })
})
