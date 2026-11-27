import { ApiError } from 'lib/api'
import { urls } from 'scenes/urls'

import type { TracePreviewApi } from '../../generated/api.schemas'
import type { CellLoads } from '../shared/cellLoads'
import { makeTraceListItem, makeTracePreview, ready } from '../traces/testFixtures'
import {
    detailLoadOf,
    isReportedFailure,
    recentTracesLoadOf,
    rowWithKey,
    scopedTracesHref,
    shownItem,
    tracesToPreview,
    valueFor,
} from './diagnosticsDrawerReads'

const REQUEST = { name: 'search_orders', params: { date_from: '-7d' } }
const PARAMS = { date_from: '-7d' }
const ROW = { key: 'c2VhcmNo', text: 'from the row' }
const DETAIL = { key: 'c2VhcmNo', text: 'from the detail' }

describe('diagnosticsDrawerReads', () => {
    it.each([
        ['the same request', REQUEST, 'read'],
        ['another entity', { ...REQUEST, name: 'get_weather' }, null],
        ['another selection', { ...REQUEST, params: { date_from: '-24h' } }, null],
        ['no open entity', null, null],
    ])('shows a value read for %s only when it answered that request', (_name, request, expected) => {
        expect(valueFor({ request: REQUEST, value: 'read' }, request)).toEqual(expected)
    })

    it.each([
        ['a read in flight', null, null, { status: 'loading' }],
        ['a read that answered', 'detail', null, { status: 'ready', value: 'detail' }],
        ['an entity with nothing in the range', null, 'not_found', { status: 'not_found' }],
        ['a failed read', null, 'failed', { status: 'error' }],
    ] as const)('shows %s', (_name, value, failure, expected) => {
        expect(detailLoadOf(value, failure)).toEqual(expected)
    })

    it('links to the traces list scoped to the entity, without the list view or any search', () => {
        const href = scopedTracesHref(
            {
                pathname: urls.aiObservabilityTools(),
                search: '?date_from=-30d&view=failing&tool_search=orders&trace_search=refund',
            },
            { date_from: '-30d', view: 'failing', tool_search: 'orders', trace_search: 'refund' },
            { kind: 'tool', value: 'search_orders' }
        )

        expect(href).toEqual(`${urls.aiObservabilityTraces()}?date_from=-30d&tool=search_orders`)
    })

    it.each([
        ['the detail over the row', DETAIL, { item: ROW, params: PARAMS }, null, DETAIL],
        ['the row while the detail loads', null, { item: ROW, params: PARAMS }, null, ROW],
        [
            'nothing from a row counted in another selection',
            null,
            { item: ROW, params: { date_from: '-24h' } },
            null,
            null,
        ],
        ['nothing for an entity not found', null, { item: ROW, params: PARAMS }, 'not_found', null],
    ] as const)('shows %s', (_name, detailItem, seed, failure, expected) => {
        expect(shownItem(detailItem, seed, { key: ROW.key, params: PARAMS }, failure)).toEqual(expected)
    })

    it('takes the text of any read of the open key, whatever its selection', () => {
        expect(rowWithKey(ROW.key, [null, { key: 'b3RoZXI', text: 'other' }, ROW])).toEqual(ROW)
        expect(rowWithKey(null, [ROW])).toBeNull()
    })

    it.each([
        ['an entity not found with no text', false, 'not_found', { status: 'ready', value: [] }],
        ['a failed detail with no text', false, 'failed', { status: 'error' }],
        ['a known text whatever the detail', true, 'failed', { status: 'loading' }],
    ] as const)('shows the recent traces of %s', (_name, textKnown, failure, expected) => {
        expect(recentTracesLoadOf(null, false, textKnown, failure)).toEqual(expected)
    })

    it.each([
        ['a failed read', new ApiError('boom', 500), true],
        ['nothing found', new ApiError('missing', 404), false],
        [
            'a range too long',
            new ApiError('long', 422, undefined, { code: 'range_too_long', detail: 'Pick less.' }),
            false,
        ],
    ])('reports %s: %s', (_name, error, expected) => {
        expect(isReportedFailure(error)).toBe(expected)
    })

    it('previews only the traces with no preview read yet', () => {
        const traces = ['trace-1', 'trace-2', 'trace-3'].map((id) => makeTraceListItem({ id }))
        const previews: CellLoads<TracePreviewApi> = new Map([
            ['trace-1', ready(makeTracePreview('trace-1'))],
            ['trace-2', { status: 'error' }],
        ])

        expect(tracesToPreview(traces, previews)).toEqual(['trace-2', 'trace-3'])
    })
})
