import { getSaveAsDisabledReason, type SaveAsDisabledReasonInput } from './saveAsDisabledReason'

const ready: SaveAsDisabledReasonInput = {
    insightLoading: false,
    isSourceQueryLastRun: true,
    responseLoading: false,
    responseError: null,
    response: { results: [] },
}

describe('getSaveAsDisabledReason', () => {
    it.each([
        ['allows saving a query that ran successfully', {}, undefined],
        [
            'blocks an edited query that has not run',
            { isSourceQueryLastRun: false },
            'Run latest query changes before saving',
        ],
        ['blocks while the query runs', { responseLoading: true }, 'Running query...'],
        ['blocks a failed query', { responseError: 'Unknown table' }, 'Run query successfully before saving'],
        ['blocks a query that never ran', { response: null }, 'Run query successfully before saving'],
    ])('%s', (_, overrides, expected) => {
        expect(getSaveAsDisabledReason({ ...ready, ...overrides })).toBe(expected)
    })
})
