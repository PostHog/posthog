import { act, renderHook } from '@testing-library/react'
import type { editor } from 'monaco-editor'

import { useTemplateEditorCursor } from './CyclotronJobTemplateSuggestions'
import {
    CyclotronJobTemplateOption,
    insertTemplateReference,
    templateReferenceForOption,
} from './cyclotronJobTemplateSuggestionsLogic'

const optionFor = (example: string): CyclotronJobTemplateOption => ({
    key: 'example',
    description: 'An example',
    example,
})

describe('cyclotron job template suggestions', () => {
    describe('templateReferenceForOption', () => {
        it.each([
            ['a hog expression is wrapped in braces', 'hog', `$1 ?? 'Default value'`, `{$1 ?? 'Default value'}`],
            ['a hog function call is wrapped in braces', 'hog', 'concat($1, $2)', '{concat($1, $2)}'],
            [
                'a liquid output tag keeps its own braces',
                'liquid',
                '{{ person.properties.email }}',
                '{{ person.properties.email }}',
            ],
            [
                'a liquid block tag keeps its own braces',
                'liquid',
                '{% if condition %} Yes {% else %} No {% endif %}',
                '{% if condition %} Yes {% else %} No {% endif %}',
            ],
            [
                'a bare liquid expression is wrapped in output braces',
                'liquid',
                'person.properties.email',
                '{{ person.properties.email }}',
            ],
        ] as [string, 'hog' | 'liquid', string, string][])('%s', (_name, templating, example, expected) => {
            expect(templateReferenceForOption(optionFor(example), templating)).toBe(expected)
        })
    })

    it.each([false, true])('inserts at the initial cursor when the editor starts focused: %s', (startsFocused) => {
        let focusEditor = (): void => {}
        let moveCursor = (): void => {}
        let column = 1
        const disposeCursor = jest.fn()
        const disposeFocus = jest.fn()
        const editorInstance = {
            getPosition: () => ({ lineNumber: 1, column }),
            getModel: () => ({ getOffsetAt: (position: { column: number }) => position.column - 1 }),
            hasTextFocus: () => startsFocused,
            onDidChangeCursorPosition: (callback: () => void) => {
                moveCursor = callback
                return { dispose: disposeCursor }
            },
            onDidFocusEditorText: (callback: () => void) => {
                focusEditor = callback
                return { dispose: disposeFocus }
            },
        } as unknown as editor.IStandaloneCodeEditor
        const { result, unmount } = renderHook(() => useTemplateEditorCursor())
        act(() => result.current.onEditorMount(editorInstance))
        if (!startsFocused) {
            expect(insertTemplateReference('Hi there', '{person.name}', result.current.cursorOffset())).toBe(
                'Hi there{person.name}'
            )
            act(() => focusEditor())
        }
        expect(insertTemplateReference('Hi there', '{person.name}', result.current.cursorOffset())).toBe(
            '{person.name}Hi there'
        )
        column = 4
        act(() => moveCursor())
        expect(insertTemplateReference('Hi there', '{person.name}', result.current.cursorOffset())).toBe(
            'Hi {person.name}there'
        )
        unmount()
        expect(disposeCursor).toHaveBeenCalledTimes(1)
        expect(disposeFocus).toHaveBeenCalledTimes(1)
    })

    describe('insertTemplateReference', () => {
        it.each([
            ['at a cursor in the middle of the text', 'Hi , welcome', 3, 'Hi {person.name}, welcome'],
            ['at a cursor at the start of the text', 'Hi there', 0, '{person.name}Hi there'],
            ['at a cursor at the end of the text', 'Hi there', 8, 'Hi there{person.name}'],
            ['into empty text', '', 0, '{person.name}'],
        ] as [string, string, number, string][])('inserts %s', (_name, value, cursorOffset, expected) => {
            expect(insertTemplateReference(value, '{person.name}', cursorOffset)).toBe(expected)
        })

        it.each([
            ['the cursor position is unknown', null],
            ['the tracked cursor is past the end of the current text', 99],
        ] as [string, number | null][])('appends when %s', (_name, cursorOffset) => {
            expect(insertTemplateReference('Hi there', '{person.name}', cursorOffset)).toBe('Hi there{person.name}')
        })
    })
})
