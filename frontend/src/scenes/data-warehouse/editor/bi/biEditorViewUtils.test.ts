import { SQLEditorMode } from '../sqlEditorModes'
import { BIEditorView } from './biEditorTypes'
import { canUseBIEditor, shouldConfirmEnteringBIEditor } from './biEditorViewUtils'

describe('BI editor view behavior', () => {
    test.each([
        ['the flag is disabled', false, SQLEditorMode.FullScene, false],
        ['the editor is embedded', true, SQLEditorMode.Embedded, false],
        ['raw SQL is enabled', true, SQLEditorMode.FullScene, true],
    ])('is unavailable when %s', (_name, featureEnabled, mode, sendRawQueryEnabled) => {
        expect(canUseBIEditor(featureEnabled, mode, sendRawQueryEnabled)).toBe(false)
    })

    it('is available in the full editor when HogQL translation is enabled', () => {
        expect(canUseBIEditor(true, SQLEditorMode.FullScene, false)).toBe(true)
    })

    test.each([
        ['an empty query', BIEditorView.BI, '  ', null],
        ['SQL mode is selected', BIEditorView.SQL, 'SELECT 1', null],
        [
            'the SQL still matches the generated query',
            BIEditorView.BI,
            'SELECT 1',
            { query: 'SELECT 1', node: {} as never },
        ],
    ])('does not require confirmation when %s', (_name, nextEditorView, queryInput, generatedQuery) => {
        expect(shouldConfirmEnteringBIEditor(nextEditorView, queryInput, generatedQuery)).toBe(false)
    })

    it('requires confirmation before Builder can replace edited SQL', () => {
        expect(
            shouldConfirmEnteringBIEditor(BIEditorView.BI, 'SELECT 2', {
                query: 'SELECT 1',
                node: {} as never,
            })
        ).toBe(true)
    })
})
