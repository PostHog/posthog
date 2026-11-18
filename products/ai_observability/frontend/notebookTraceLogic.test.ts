import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { notebookTraceLogic } from './notebookTraceLogic'
import { parserRecipesLogic } from './settings/parserRecipesLogic'

describe('notebookTraceLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it("loads the team's parser recipes, so a widget opened on its own renders custom message shapes", () => {
        notebookTraceLogic({ traceId: 'trace-1' }).mount()

        expect(parserRecipesLogic.isMounted()).toBe(true)
    })

    it('asks for the trace over the last year with sentiment', () => {
        jest.useFakeTimers().setSystemTime(new Date('2026-11-12T15:30:00Z'))
        const logic = notebookTraceLogic({ traceId: 'trace-1' })
        logic.mount()

        expect(logic.values.query).toEqual({
            kind: NodeKind.TraceQuery,
            traceId: 'trace-1',
            includeSentiment: true,
            dateRange: { date_from: '2025-11-12T00:00:00.000Z' },
        })
    })

    it.each([
        ['the first trace of the results', { results: [{ id: 'trace-1', events: [] }] }, 'trace-1'],
        ['nothing for an empty result', { results: [] }, undefined],
        ['nothing for a response that is not a trace', { results: [{ name: 'not a trace' }] }, undefined],
    ])('reads %s', (_name, response, expectedId) => {
        const logic = notebookTraceLogic({ traceId: 'trace-1' })
        logic.mount()

        dataNodeLogic(logic.values.dataNodeProps).actions.setResponse(response)

        expect(logic.values.trace?.id).toBe(expectedId)
    })
})
