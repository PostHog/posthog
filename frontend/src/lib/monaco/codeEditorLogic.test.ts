import { expectLogic } from 'kea-test-utils'

import * as queryRunner from '~/queries/query'
import { HogLanguage, HogQLMetadataResponse, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { codeEditorLogic, CodeEditorLogicProps } from './codeEditorLogic'

jest.mock('monaco-editor', () => ({ MarkerSeverity: { Error: 8, Warning: 4, Hint: 1 } }))

const response: HogQLMetadataResponse = {
    isValid: false,
    errors: [
        {
            code: 'TRINO_PURE_ACTION_UNSUPPORTED',
            message: 'Actions require PostHog semantic expansion.',
            start: 7,
            end: 23,
        },
    ],
    warnings: [],
    notices: [],
}

const source: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: 'SELECT matchesAction(1)',
    connectionId: 'trino-1',
    values: { status: 'paid' },
    filters: { dateRange: { date_from: '-7d' } },
    modifiers: { convertToProjectTimezone: true },
}

function buildEditor(onMetadata = jest.fn()): ReturnType<typeof codeEditorLogic.build> {
    const model = { getPositionAt: (offset: number) => ({ lineNumber: 1, column: offset + 1 }) }
    const logic = codeEditorLogic({
        key: 'trino-metadata',
        query: source.query,
        language: HogLanguage.hogQL,
        sourceQuery: source,
        editor: { getModel: () => model } as unknown as CodeEditorLogicProps['editor'],
        monaco: { editor: { setModelMarkers: jest.fn() } } as unknown as CodeEditorLogicProps['monaco'],
        onMetadata,
    })
    logic.mount()
    return logic
}

describe('Trino Editor metadata', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => jest.restoreAllMocks())

    it('validates the execution inputs and preserves diagnostic codes in Monaco markers', async () => {
        const performQuery = jest.spyOn(queryRunner, 'performQuery').mockResolvedValue(response)
        const logic = buildEditor()
        await expectLogic(logic, () => logic.actions.reloadMetadata()).toFinishAllListeners()
        expect(performQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                connectionId: source.connectionId,
                globals: source.values,
                filters: source.filters,
                modifiers: source.modifiers,
            })
        )
        expect(logic.values.modelMarkers).toEqual([
            expect.objectContaining({ code: response.errors[0].code, severity: 8 }),
        ])
    })

    it('ignores a response for the previous connection after switching targets', async () => {
        let resolvePrevious!: (value: HogQLMetadataResponse) => void
        let requestStarted!: () => void
        const started = new Promise<void>((resolve) => {
            requestStarted = resolve
        })
        const current: HogQLMetadataResponse = { isValid: true, errors: [], warnings: [], notices: [] }
        jest.spyOn(queryRunner, 'performQuery')
            .mockImplementationOnce(() => {
                requestStarted()
                return new Promise<HogQLMetadataResponse>((resolve) => {
                    resolvePrevious = resolve
                })
            })
            .mockResolvedValue(current)
        const onMetadata = jest.fn()
        const logic = buildEditor(onMetadata)
        logic.actions.reloadMetadata()
        await started
        await expectLogic(logic, () => {
            codeEditorLogic({ ...logic.props, sourceQuery: { ...source, connectionId: 'trino-2' } })
        }).toDispatchActions(['reloadMetadataSuccess'])
        resolvePrevious(response)
        await expectLogic(logic).toFinishAllListeners()
        expect(onMetadata).toHaveBeenCalledTimes(1)
        expect(onMetadata).toHaveBeenLastCalledWith(current)
        expect(logic.values.modelMarkers).toEqual([])
    })
})
