import { decodeParams, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { initKeaTests } from '~/test/init'

import { TRACE_PAGE_HOST_ID, tracePageLogic } from './tracePageLogic'
import { traceViewHostLogic } from './traceViewHostLogic'

describe('tracePageLogic', () => {
    let logic: ReturnType<typeof tracePageLogic.build>
    let host: ReturnType<typeof traceViewHostLogic.build>

    beforeEach(() => {
        initKeaTests()
        host = traceViewHostLogic({ hostId: TRACE_PAGE_HOST_ID })
        host.mount()
        logic = tracePageLogic()
        logic.mount()
    })

    const open = (search: string, id = 'trace-1'): void => {
        const pathname = `${urls.aiObservabilityTraces()}/${id}`
        // The raw search string reaches the logic as it does on a page load, before kea-router parses it.
        router.actions.locationChanged({
            method: 'POP',
            pathname,
            search,
            searchParams: decodeParams(search, '?'),
            hash: '',
            hashParams: {},
            url: `${pathname}${search}`,
        })
    }

    it.each([
        ['event', '?event=gen-1', { requestedStepId: 'gen-1', openingMode: null }],
        ['tab=summary', '?tab=summary', { requestedStepId: null, openingMode: 'summary', detailTab: 'messages' }],
        [
            'tab=evals with no event',
            '?tab=evals',
            { requestedStepId: 'trace-1', openingMode: null, detailTab: 'evals' },
        ],
        ['tab=evals with an event', '?tab=evals&event=gen-1', { requestedStepId: 'gen-1', detailTab: 'evals' }],
        ['another tab', '?tab=conversation', { requestedStepId: null, openingMode: null, detailTab: 'messages' }],
        ['search', '?search=refund', { seedQuery: 'refund' }],
        ['a numeric search keeps its text', '?search=1.50', { seedQuery: '1.50' }],
    ])('reads %s from the URL', (_name, search, expected) => {
        open(search)

        expect(logic.values.traceId).toBe('trace-1')
        expect(host.values).toMatchObject(expected)
    })

    it('decodes an encoded trace id', () => {
        open('', 'a%2Fb')

        expect(logic.values.traceId).toBe('a/b')
    })

    it.each([
        ['timestamp', '?timestamp=2026-01-01T12:00:00Z', '2026-01-01T12:00:00Z'],
        [
            'a timestamp whose plus sign decoded to a space',
            '?timestamp=2026-01-01T12:00:00 00:00',
            '2026-01-01T12:00:00+00:00',
        ],
        ['exception_ts', '?exception_ts=2026-01-01T12:00:00Z', '2026-01-01T11:40:00.000Z'],
    ])('derives the timestamp hint from %s', (_name, search, expected) => {
        open(search)

        expect(logic.values.timestampHint).toBe(expected)
    })

    it('keeps the hint for the same trace and drops it for another', () => {
        open('?timestamp=2026-01-01T12:00:00Z')
        open('?event=gen-1')
        expect(logic.values.timestampHint).toBe('2026-01-01T12:00:00Z')

        open('', 'trace-2')
        expect(logic.values.timestampHint).toBeNull()
    })

    it('resets mode and step tab for another trace, not for the first trace or the same one', () => {
        host.actions.setMode('thread')
        host.actions.setDetailTab('raw')

        open('')
        open('?event=gen-1')
        expect(host.values).toMatchObject({ mode: 'thread', detailTab: 'raw' })

        open('', 'trace-2')
        expect(host.values).toMatchObject({ mode: 'spans', detailTab: 'messages' })
    })

    it('opens another trace on tab=evals, and keeps the tab the person picks when a step writes the URL', () => {
        open('')
        open('?tab=evals', 'trace-2')
        expect(host.values.detailTab).toBe('evals')

        host.actions.setDetailTab('raw')
        host.actions.requestStep('gen-2', 'trace-2')

        expect(router.values.searchParams).toMatchObject({ tab: 'evals', event: 'gen-2' })
        expect(host.values.detailTab).toBe('raw')
    })

    it.each([
        ['a requested step', (): void => host.actions.requestStep('gen-2', 'trace-1'), { event: 'gen-2' }],
        ['a published query', (): void => host.actions.publishQuery('x'), { search: 'x' }],
    ])('writes %s to the URL and keeps the other params and the hash', (_name, write, expected) => {
        open('?back_to=generations')
        router.actions.replace(router.values.location.pathname, router.values.searchParams, { panel: 'discussion' })

        write()

        expect(router.values.searchParams).toMatchObject({ ...expected, back_to: 'generations' })
        expect(router.values.hashParams).toEqual({ panel: 'discussion' })
    })

    it.each(['1.50', '2e3'])('keeps the raw search %s when a step is written', (query) => {
        open(`?search=${query}`)

        host.actions.requestStep('gen-2', 'trace-1')

        expect(new URLSearchParams(router.values.location.search).get('search')).toBe(query)
        expect(host.values.seedQuery).toBe(query)
    })

    it.each([
        ['a step the URL already omits', '', (): void => host.actions.requestStep(null, 'trace-1')],
        ['a query the URL already holds', '?search=1.50', (): void => host.actions.publishQuery('1.50')],
    ])('does not write the URL for %s', (_name, search, write) => {
        open(search)
        const replace = jest.spyOn(router.actions, 'replace')

        write()

        expect(replace).not.toHaveBeenCalled()
        replace.mockRestore()
    })

    it.each(['1.50', '[draft]'])('keeps the typed search %s when the browser restores its URL', (query) => {
        open('')
        host.actions.publishQuery(query)

        // Back and forward decode the URL again, as a page load does.
        open(router.values.location.search)

        expect(host.values.seedQuery).toBe(query)
    })

    it('derives the back link from the URL', () => {
        open('?back_to=reviews')

        expect(logic.values.backLink.label).toBe('Back to reviews')
    })

    // Regression: an override left behind on unmount keeps the nav collapsed on every other page.
    it.each([
        ['expanded', false],
        ['collapsed', true],
    ])('collapses the nav while open and restores it %s on close', (_name, collapsedBefore) => {
        logic.unmount()
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.setLayoutNavCollapsedDesktop(collapsedBefore)

        logic = tracePageLogic()
        logic.mount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)
        logic.unmount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(collapsedBefore)
    })
})
