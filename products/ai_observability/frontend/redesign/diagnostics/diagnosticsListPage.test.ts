import { AiObservabilityToolsListOrder, AiObservabilityToolsListView } from '../../generated/api.schemas'
import type { SelectionNarrowingParams } from '../lists/listParams'
import {
    DiagnosticsPageSummary,
    ShownDiagnosticsPage,
    diagnosticsListParams,
    diagnosticsListState,
    enumValue,
} from './diagnosticsListPage'

const SCOPE = { dateFrom: '-7d', dateTo: null, filterTestAccounts: false }
const NO_FILTERS = { propertyFilters: [], search: '', quickFilter: null, scope: null }
const BASE_PARAMS = { date_from: '-7d', filter_test_accounts: false }

function shown(
    count: number,
    nothingCaptured: boolean,
    params: SelectionNarrowingParams = BASE_PARAMS
): ShownDiagnosticsPage<DiagnosticsPageSummary, SelectionNarrowingParams> {
    return { page: { count, nothingCaptured }, request: { pageIndex: 0, params } }
}

describe('diagnosticsListPage', () => {
    it.each([
        ['a value the api knows', 'failure_rate', 'failure_rate'],
        ["another tab's value", 'occurrences', null],
        ['no value', null, null],
    ])('reads %s', (_name, raw, expected) => {
        expect(enumValue(AiObservabilityToolsListOrder, raw)).toEqual(expected)
    })

    it.each([
        ['a view the api knows', 'failing', 'failing'],
        ["another tab's view", 'increasing', undefined],
    ])('sends %s', (_name, quickFilter, view) => {
        const params = diagnosticsListParams(
            { ...NO_FILTERS, quickFilter, search: 'lookup' },
            SCOPE,
            AiObservabilityToolsListView,
            AiObservabilityToolsListOrder.Calls
        )

        expect(params).toMatchObject({ ...BASE_PARAMS, search: 'lookup', order: 'calls', view })
    })

    it.each([
        ['no page has answered', null, null, 'loading'],
        ['the first page failed', null, new Error('boom'), 'error'],
        ['the page has rows', shown(3, false), null, 'ready'],
        ['nothing narrows the selection', shown(0, false), null, 'empty'],
        ['a filter is on', shown(0, false, { ...BASE_PARAMS, properties: '[]' }), null, 'empty-filtered'],
        ['a search is on', shown(0, false, { ...BASE_PARAMS, search: 'lookup' }), null, 'empty-filtered'],
        ['a view is on', shown(0, false, { ...BASE_PARAMS, view: 'failing' }), null, 'empty-filtered'],
        [
            'test accounts are left out',
            shown(0, false, { ...BASE_PARAMS, filter_test_accounts: true }),
            null,
            'empty-filtered',
        ],
        ['nothing was ever captured, even with a search on', shown(0, true, { search: 'lookup' }), null, 'empty'],
        ['a later page failed over rows', shown(3, false), new Error('boom'), 'ready'],
    ])('shows %s', (_name, page, pageError, state) => {
        expect(diagnosticsListState(page, pageError)).toEqual(state)
    })
})
