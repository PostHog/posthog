import { cleanup, render } from '@testing-library/react'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { initKeaTests } from '~/test/init'

import { ListTable, ListTableProps, ListTableState } from './ListTable'

interface Row {
    id: string
    name: string
}

const ROWS: Row[] = [
    { id: 'trace-a', name: 'rag-query' },
    { id: 'trace-b', name: 'support-reply' },
]

const COLUMNS: LemonTableColumns<Row> = [{ title: 'Name', dataIndex: 'name' }]

function renderTable(props: Partial<ListTableProps<Row>> = {}): HTMLElement {
    initKeaTests()
    return render(
        <ListTable<Row>
            state="ready"
            columns={COLUMNS}
            rows={ROWS}
            rowKey={(row) => row.id}
            refreshing={false}
            emptyState={<div data-attr="empty">No traces yet</div>}
            emptyFilteredState={<div data-attr="empty-filtered">No traces match</div>}
            errorState={<div data-attr="error">Could not load</div>}
            data-attr="traces-list"
            {...props}
        />
    ).container
}

function shownRowNames(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('tbody td'))
        .map((cell) => cell.textContent ?? '')
        .filter((text) => ROWS.some((row) => row.name === text))
}

function shownStates(container: HTMLElement): string[] {
    return ['empty', 'empty-filtered', 'error']
        .filter((dataAttr) => container.querySelector(`[data-attr="${dataAttr}"]`))
        .concat(container.querySelector('tbody .LemonSkeleton') ? ['skeleton'] : [])
}

function isDisabled(container: HTMLElement, dataAttr: string): boolean {
    return container.querySelector(`[data-attr="${dataAttr}"]`)?.getAttribute('aria-disabled') === 'true'
}

describe('ListTable', () => {
    afterEach(cleanup)

    it.each<[ListTableState, boolean, string[], string[], boolean]>([
        ['loading', false, [], ['skeleton'], true],
        ['ready', false, ['rag-query', 'support-reply'], [], false],
        ['ready', true, ['rag-query', 'support-reply'], [], true],
        ['empty', false, [], ['empty'], false],
        ['empty-filtered', false, [], ['empty-filtered'], false],
        ['error', false, [], ['error'], false],
    ])('in %s, refreshing %s, shows rows %j and %j', (state, refreshing, rowNames, states, dimmed) => {
        const container = renderTable({ state, refreshing })

        expect(shownRowNames(container)).toEqual(rowNames)
        expect(shownStates(container)).toEqual(states)
        expect(container.querySelector('.LemonTable--loading') !== null).toBe(dimmed)
    })

    it('says a page with no rows and a next page has nothing to show, not that the list is empty', () => {
        const container = renderTable({ rows: [], onNext: () => {} })

        expect(container.textContent).toContain('Nothing to show on this page')
        expect(shownStates(container)).toEqual([])
        expect(isDisabled(container, 'traces-list-next-page')).toBe(false)
    })

    it.each<[string, Partial<ListTableProps<Row>>, boolean, boolean]>([
        ['first page', { onNext: () => {} }, true, false],
        ['last page', { onPrevious: () => {} }, false, true],
        ['middle page', { onPrevious: () => {}, onNext: () => {} }, false, false],
    ])('on the %s disables only the pager buttons with no handler', (_, handlers, previousDisabled, nextDisabled) => {
        const container = renderTable(handlers)

        expect(isDisabled(container, 'traces-list-previous-page')).toBe(previousDisabled)
        expect(isDisabled(container, 'traces-list-next-page')).toBe(nextDisabled)
    })

    it.each<[string, Partial<ListTableProps<Row>>]>([
        ['loading', { state: 'loading' }],
        ['refreshing', { refreshing: true }],
    ])('disables both pager buttons while a page is %s', (_, loadingProps) => {
        const container = renderTable({ ...loadingProps, onPrevious: () => {}, onNext: () => {} })

        const pager = Array.from(container.querySelectorAll('[aria-label="Previous page"], [aria-label="Next page"]'))
        expect(pager.map((button) => button.getAttribute('aria-disabled'))).toEqual(['true', 'true'])
    })
})
