import { expectLogic } from 'kea-test-utils'

import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'

import { performQuery } from '~/queries/query'
import { HogLanguage, HogQLMetadataResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

describe('codeEditorLogic', () => {
    const setModelMarkers = jest.fn()

    const buildModel = (text: string): any => ({
        getValue: () => text,
        getPositionAt: (offset: number) => {
            const before = text.slice(0, offset)
            const lines = before.split('\n')
            return { lineNumber: lines.length, column: lines[lines.length - 1].length + 1 }
        },
    })

    const mountLogic = (modelText: string, metadataQuery: string, metadataQueryOffset: number): any => {
        const editor = { getModel: () => buildModel(modelText) }
        const logic = codeEditorLogic({
            key: 'test',
            query: modelText,
            metadataQuery,
            metadataQueryOffset,
            language: HogLanguage.hogQL,
            editor: editor as any,
            monaco: { editor: { setModelMarkers } } as any,
        })
        logic.mount()
        return logic
    }

    const respondWith = (response: Partial<HogQLMetadataResponse>): void => {
        ;(performQuery as jest.Mock).mockResolvedValue({ errors: [], warnings: [], notices: [], ...response })
    }

    beforeEach(() => {
        initKeaTests()
        setModelMarkers.mockClear()
        ;(performQuery as jest.Mock).mockReset()
    })

    it('keeps an error without a position off the lines it does not describe', async () => {
        const query = 'SELECT 1\nFROM events\nWHERE event = 1'
        respondWith({ errors: [{ message: 'Syntax error' }] })
        const logic = mountLogic(query, query, 0)

        await expectLogic(logic, () => logic.actions.reloadMetadata()).toFinishAllListeners()

        expect(logic.values.modelMarkers).toHaveLength(1)
        expect(logic.values.modelMarkers[0]).toMatchObject({
            startLineNumber: 1,
            startColumn: 1,
            endLineNumber: 1,
            endColumn: 9,
            message: 'Syntax error',
        })
    })

    it('does not paint markers from a response for text the editor no longer holds', async () => {
        respondWith({ errors: [{ message: 'Syntax error', start: 0, end: 6 }] })
        // The editor text was replaced, but the metadata query still points at the previous statement.
        const logic = mountLogic('SELECT 1', 'SELECT 2', 0)

        await expectLogic(logic, () => logic.actions.reloadMetadata()).toFinishAllListeners()

        expect(logic.values.modelMarkers).toEqual([])
        expect(setModelMarkers).not.toHaveBeenCalled()
    })
})
