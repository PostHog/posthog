import {
    appendedPages,
    canStepBack,
    firstPageParams,
    listStateOf,
    nextPageStep,
    pageIndexAfterLoad,
    readAbortablePage,
    listRequestParams,
} from './cursorPaging'
import type { ListFilters } from './listFiltersLogic'

const page = (items: string[], nextCursor: string | null): { items: string[]; nextCursor: string | null } => ({
    items,
    nextCursor,
})
const never = (): boolean => false

describe('cursorPaging', () => {
    it.each([
        ['a first page replaces the pages', undefined, ['b'], 0],
        ['a next page is appended and shown', { cursor: 'c2' }, ['a', 'b'], 1],
    ])('%s', (_name, payload, pages, index) => {
        expect(appendedPages(['a'], 'b', payload)).toEqual(payload ? pages : ['b'])
        expect(pageIndexAfterLoad(0, payload)).toEqual(index)
    })

    it('keeps the first page params when a next page lands', () => {
        const first: { limit: number; cursor?: string } = { limit: 50 }
        expect(firstPageParams(null, first)).toBe(first)
        expect(firstPageParams(first, { limit: 50, cursor: 'c2' })).toBe(first)
    })

    it('does not step back while a read is in flight', () => {
        expect([canStepBack(1, false), canStepBack(1, true), canStepBack(0, false)]).toEqual([true, false, false])
    })

    it.each([
        ['loading', [], false, 'loading'],
        ['a failure with no rows', [], true, 'error'],
        ['an empty first page', [page([], null)], false, 'empty'],
        ['a first page with no rows but a next page', [page([], 'c2')], false, 'ready'],
        ['rows', [page(['a'], null)], false, 'ready'],
    ])('reads %s as the %s state', (_name, pages, pageFailed, state) => {
        expect(listStateOf(pages, pageFailed, null, never)).toEqual(state)
    })

    it('tells an empty selection that filters narrowed from one that nothing narrowed', () => {
        expect(listStateOf([page([], null)], false, { narrowed: true }, (params) => !!params?.narrowed)).toEqual(
            'empty-filtered'
        )
    })

    it.each([
        [
            'shows a page in memory',
            { pages: [page(['a'], 'c2'), page(['b'], null)], pageIndex: 0, pagesParams: {}, pageLoading: false },
            { show: 1 },
        ],
        [
            'reads the next page with the first page params',
            { pages: [page(['a'], 'c2')], pageIndex: 0, pagesParams: { limit: 50 }, pageLoading: false },
            { load: { limit: 50, cursor: 'c2' } },
        ],
        [
            'waits while a read is in flight',
            { pages: [page(['a'], 'c2')], pageIndex: 0, pagesParams: { limit: 50 }, pageLoading: true },
            null,
        ],
        [
            'stops on the last page',
            { pages: [page(['a'], null)], pageIndex: 0, pagesParams: { limit: 50 }, pageLoading: false },
            null,
        ],
    ])('%s', (_name, state, step) => {
        expect(nextPageStep(state)).toEqual(step)
    })

    it('aborts the read on dispose and drops a superseded failure', async () => {
        let dispose = (): void => {}
        const cache = {
            disposables: {
                add: (setup: () => () => void): void => {
                    dispose = setup()
                },
            },
        }
        let signal: AbortSignal | undefined
        const superseded = (): void => {
            throw new Error('superseded')
        }

        await expect(
            readAbortablePage(
                cache,
                (readSignal) => {
                    signal = readSignal
                    return Promise.reject(new Error('boom'))
                },
                superseded
            )
        ).rejects.toThrow('superseded')
        dispose()

        expect(signal?.aborted).toBe(true)
    })

    it('sends the search only when it is enabled', () => {
        const filters: ListFilters = { propertyFilters: [], search: 'refund', quickFilter: null }
        const scope = { dateFrom: '-7d', dateTo: null, filterTestAccounts: false }

        expect(listRequestParams(filters, { ...scope, searchEnabled: true }).search).toEqual('refund')
        expect(listRequestParams(filters, { ...scope, searchEnabled: false }).search).toBeUndefined()
    })
})
