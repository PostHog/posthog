import { cleanup, fireEvent, render, renderHook } from '@testing-library/react'
import { router } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

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

describe('useTracesQueryContext row navigation', () => {
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
