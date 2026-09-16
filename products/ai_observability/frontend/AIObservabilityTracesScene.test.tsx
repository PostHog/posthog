import { cleanup, fireEvent, render, renderHook } from '@testing-library/react'
import { router } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContextColumnComponent } from '~/queries/types'
import { initKeaTests } from '~/test/init'

import { useTracesQueryContext } from './AIObservabilityTracesScene'

jest.mock('lib/utils/newInternalTab')

const TRACE_RECORD = { result: { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z', events: [] } }
const TRACE_PATH = urls.aiObservabilityTrace('trace-1')
const LINK_CELL_PATH = urls.aiObservabilitySessions()

function renderRow(record: unknown): { plainCell: HTMLElement; linkCell: HTMLElement } {
    const { result } = renderHook(() => useTracesQueryContext())
    const { getByTestId } = render(
        <table>
            <tbody>
                <tr {...(result.current.rowProps?.(record) ?? {})}>
                    <td data-attr="plain-cell">plain</td>
                    <td>
                        <Link to={LINK_CELL_PATH} data-attr="link-cell">
                            link
                        </Link>
                    </td>
                </tr>
            </tbody>
        </table>
    )
    return { plainCell: getByTestId('plain-cell'), linkCell: getByTestId('link-cell') }
}

function renderCell(columnName: string, record: unknown): string {
    const { result } = renderHook(() => useTracesQueryContext())
    const Column = result.current.columns?.[columnName]?.render as QueryContextColumnComponent
    const { container } = render(
        <Column
            record={record}
            columnName={columnName}
            value={undefined}
            query={{} as DataTableNode}
            recordIndex={0}
            rowCount={1}
        />
    )
    return container.textContent ?? ''
}

describe('useTracesQueryContext', () => {
    describe('row navigation', () => {
        let pathnameBeforeClick: string

        beforeEach(() => {
            cleanup()
            initKeaTests()
            jest.mocked(newInternalTab).mockClear()
            pathnameBeforeClick = router.values.location.pathname
        })

        it('navigates to the trace detail view when a plain cell is clicked', () => {
            const { plainCell } = renderRow(TRACE_RECORD)

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toContain(TRACE_PATH)
            expect(router.values.searchParams).toMatchObject({ back_to: 'traces', timestamp: '2026-01-01T11:55:00Z' })
            expect(newInternalTab).not.toHaveBeenCalled()
        })

        it.each([
            ['meta-click', (cell: HTMLElement): boolean => fireEvent.click(cell, { metaKey: true })],
            ['ctrl-click', (cell: HTMLElement): boolean => fireEvent.click(cell, { ctrlKey: true })],
            [
                'middle click',
                (cell: HTMLElement): boolean =>
                    fireEvent(cell, new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 })),
            ],
        ])('opens the trace detail view in a new tab on %s', (_name, clickCell) => {
            const { plainCell } = renderRow(TRACE_RECORD)

            clickCell(plainCell)

            expect(router.values.location.pathname).toBe(pathnameBeforeClick)
            expect(newInternalTab).toHaveBeenCalledWith(expect.stringContaining(TRACE_PATH))
        })

        it('leaves a cell with its own link to handle its click', () => {
            const { linkCell } = renderRow(TRACE_RECORD)

            fireEvent.click(linkCell)

            expect(router.values.location.pathname).toContain(LINK_CELL_PATH)
            expect(newInternalTab).not.toHaveBeenCalled()
        })

        it.each([
            ['has no createdAt', { id: 'trace-1', events: [] }],
            ['has an unparseable createdAt', { id: 'trace-1', createdAt: 'not a date', events: [] }],
        ])('leaves the timestamp out of the trace detail url when the row %s', (_name, result) => {
            const { plainCell } = renderRow({ result })

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toContain(TRACE_PATH)
            expect(router.values.searchParams).not.toHaveProperty('timestamp')
        })

        it.each([
            ['a label row', { label: 'January 1' }],
            ['an array result', { result: ['trace-1'] }],
            ['a result without an id', { result: { createdAt: '2026-01-01T12:00:00Z' } }],
        ])('does not make the row clickable for %s', (_name, record) => {
            const { plainCell } = renderRow(record)

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toBe(pathnameBeforeClick)
            expect(newInternalTab).not.toHaveBeenCalled()
        })
    })

    // A row the response returned without a field `LLMTrace` types as present used to throw
    // in the cell renderer, which reaches the scene error boundary and blanks the whole list.
    describe('malformed cells', () => {
        beforeEach(() => {
            cleanup()
            initKeaTests()
        })

        it.each([
            ['id', { createdAt: '2026-01-01T12:00:00Z', events: [] }],
            ['createdAt', { id: 'trace-1', events: [] }],
            ['promptVersion', { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z' }],
            ['promptVersionId', { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z' }],
        ])('renders the %s cell as a dash instead of throwing', (columnName, record) => {
            expect(renderCell(columnName, record)).toBe('–')
        })

        it('renders the trace name as plain text when the row has no id', () => {
            expect(renderCell('traceName', { traceName: 'my trace' })).toBe('my trace')
        })
    })
})
