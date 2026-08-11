import {
    TemplateLanguage,
    insideTemplateExpression,
    retriggerSuggestionsAfterDeletion,
} from 'lib/monaco/suggestionRetrigger'

import { HogLanguage } from '~/queries/schema/schema-general'

type ContentChangeListener = (event: {
    isFlush: boolean
    changes: Array<{ text: string; rangeLength: number }>
}) => void

/** The slice of IStandaloneCodeEditor the retrigger reads, driven by hand in the tests. */
function fakeEditor(textBeforeCursor: string): {
    editor: any
    trigger: jest.Mock
    delete_: () => void
    insert: () => void
} {
    let listener: ContentChangeListener | null = null
    const trigger = jest.fn()
    const editor = {
        onDidChangeModelContent: (callback: ContentChangeListener) => {
            listener = callback
            return { dispose: () => (listener = null) }
        },
        hasTextFocus: () => true,
        getModel: () => ({
            getValue: () => textBeforeCursor,
            getOffsetAt: () => textBeforeCursor.length,
        }),
        getPosition: () => ({ lineNumber: 1, column: textBeforeCursor.length + 1 }),
        trigger,
    }
    return {
        editor,
        trigger,
        delete_: () => listener?.({ isFlush: false, changes: [{ text: '', rangeLength: 1 }] }),
        insert: () => listener?.({ isFlush: false, changes: [{ text: 'a', rangeLength: 0 }] }),
    }
}

describe('suggestionRetrigger', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each<[TemplateLanguage, string, boolean]>([
        [HogLanguage.hogTemplate, 'Hi {person.pro', true],
        [HogLanguage.hogTemplate, 'Hi {f({a: 1})', true],
        [HogLanguage.hogTemplate, 'Hi {person.properties.name} ', false],
        [HogLanguage.hogTemplate, 'escaped \\{ brace ', false],
        [HogLanguage.liquid, '{{ person.pro', true],
        [HogLanguage.liquid, '{% if person.pro', true],
        [HogLanguage.liquid, '{{ person.properties.name }} ', false],
        [HogLanguage.liquid, 'Hi there ', false],
    ])('insideTemplateExpression for %s with %p is %p', (language, before, expected) => {
        expect(insideTemplateExpression(before, language)).toBe(expected)
    })

    test('a burst of deletions fires a single trigger only after the pause', () => {
        const { editor, trigger, delete_ } = fakeEditor('Hi {person.pro')
        retriggerSuggestionsAfterDeletion(editor, HogLanguage.hogTemplate)

        for (let i = 0; i < 10; i++) {
            delete_()
            jest.advanceTimersByTime(50)
        }
        expect(trigger).not.toHaveBeenCalled()

        jest.advanceTimersByTime(300)
        expect(trigger).toHaveBeenCalledTimes(1)
        expect(trigger).toHaveBeenCalledWith('deletionRetrigger', 'editor.action.triggerSuggest', {})
    })

    test('an insertion after a deletion cancels the pending reopen', () => {
        const { editor, trigger, delete_, insert } = fakeEditor('Hi {person.pro')
        retriggerSuggestionsAfterDeletion(editor, HogLanguage.hogTemplate)

        delete_()
        insert()
        jest.advanceTimersByTime(1000)

        expect(trigger).not.toHaveBeenCalled()
    })

    test('does not reopen when the deletions leave the cursor outside an expression', () => {
        const { editor, trigger, delete_ } = fakeEditor('Hi there ')
        retriggerSuggestionsAfterDeletion(editor, HogLanguage.hogTemplate)

        delete_()
        jest.advanceTimersByTime(1000)

        expect(trigger).not.toHaveBeenCalled()
    })

    test('disposal cancels a pending reopen', () => {
        const { editor, trigger, delete_ } = fakeEditor('Hi {person.pro')
        const disposable = retriggerSuggestionsAfterDeletion(editor, HogLanguage.hogTemplate)

        delete_()
        disposable.dispose()
        jest.advanceTimersByTime(1000)

        expect(trigger).not.toHaveBeenCalled()
    })
})
