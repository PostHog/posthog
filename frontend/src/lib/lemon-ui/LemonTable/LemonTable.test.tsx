import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { LemonTable } from './LemonTable'

interface Row {
    id: number
    name: string
    value: number
}

const DATA: Row[] = [
    { id: 1, name: 'alpha', value: 3 },
    { id: 2, name: 'beta', value: 1 },
    { id: 3, name: 'gamma', value: 2 },
]

const COLUMNS = [
    {
        title: 'Value',
        key: 'value',
        render: (_: any, row: Row) => <span data-attr="cell-name">{row.name}</span>,
        sorter: (a: Row, b: Row) => a.value - b.value,
    },
]

describe('LemonTable', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    const renderedOrder = (): string[] => screen.getAllByTestId('cell-name').map((el) => el.textContent ?? '')

    it.each([
        [true, ['alpha', 'gamma', 'beta']],
        [false, ['alpha', 'beta', 'gamma']],
    ])('useURLForSorting=%s reads the order search param only when enabled', (useURLForSorting, expectedOrder) => {
        router.actions.push(router.values.location.pathname, { order: '-value' })
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={COLUMNS}
                useURLForSorting={useURLForSorting as boolean}
            />
        )
        expect(renderedOrder()).toEqual(expectedOrder)
    })

    it('resizes columns and locks sibling widths', () => {
        const onResize = jest.fn()
        const onSecondColumnResize = jest.fn()
        const onResizeEnd = jest.fn()
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={[
                    {
                        title: 'Value',
                        key: 'value',
                        dataIndex: 'value',
                        resizable: true,
                        onResize,
                        onResizeEnd,
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        dataIndex: 'name',
                        resizable: true,
                        onResize: onSecondColumnResize,
                    },
                ]}
            />
        )
        jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
            function (this: HTMLElement): DOMRect {
                return { width: this.textContent === 'Value' ? 150 : 100 } as DOMRect
            }
        )
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback: FrameRequestCallback) => {
            callback(0)
            return 1
        })

        fireEvent.mouseDown(screen.getAllByLabelText('Resize column')[0], { button: 0, clientX: 100 })
        fireEvent.mouseMove(window, { clientX: 175 })
        fireEvent.mouseUp(window)

        expect(onResize).toHaveBeenLastCalledWith(225)
        expect(onSecondColumnResize).toHaveBeenCalledWith(100)
        expect(onResizeEnd).toHaveBeenCalledTimes(1)
    })

    it('caps a resizable column at its width so the content crops', () => {
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={[
                    {
                        title: 'Value',
                        key: 'value',
                        dataIndex: 'value',
                        width: 90,
                        resizable: true,
                        onResize: jest.fn(),
                    },
                    { title: 'Name', key: 'name', dataIndex: 'name', width: 90 },
                ]}
            />
        )

        expect(screen.getByText('Value').closest('th')).toHaveStyle({ maxWidth: '90px' })
        expect(document.querySelector('tbody tr:first-child > td')).toHaveStyle({ maxWidth: '90px' })
        expect(screen.getByText('Name').closest('th')).not.toHaveStyle({ maxWidth: '90px' })
    })

    it('leaves a cell that spans several columns uncapped', () => {
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={[
                    {
                        title: 'Value',
                        key: 'value',
                        width: 90,
                        resizable: true,
                        onResize: jest.fn(),
                        render: () => ({ children: 'spans the row', props: { colSpan: 2 } }),
                    },
                    { title: 'Name', key: 'name', dataIndex: 'name', width: 90 },
                ]}
            />
        )

        const spanningCell = document.querySelector('tbody tr:first-child > td')
        expect(spanningCell).toHaveAttribute('colspan', '2')
        expect(spanningCell).not.toHaveStyle({ maxWidth: '90px' })
        expect(spanningCell).not.toHaveClass('whitespace-nowrap')
    })

    it.each([
        ['auto', '1%'],
        ['fixed', '3rem'],
    ] as const)('reserves toggle space and expands rows with %s layout', (tableLayout, toggleWidth) => {
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA.slice(0, 1)}
                columns={COLUMNS}
                tableLayout={tableLayout}
                expandable={{ expandedRowRender: (row) => <span>{row.name} details</span> }}
            />
        )

        expect(document.querySelector('colgroup > col:first-child')).toHaveStyle({ width: toggleWidth })
        fireEvent.click(screen.getByTitle('Show more'))
        expect(screen.getByText('alpha details')).toBeInTheDocument()
        fireEvent.click(screen.getByTitle('Show less'))
        expect(screen.queryByText('alpha details')).not.toBeInTheDocument()
    })

    it('keeps headers, expanded rows, and empty states aligned when the row expansion toggle is hidden', () => {
        const { rerender } = render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={COLUMNS}
                expandable={{
                    expandedRowRender: () => <div>Expanded</div>,
                    isRowExpanded: () => true,
                    showRowExpansionToggle: false,
                    noIndent: true,
                }}
            />
        )

        const headerCells = document.querySelectorAll('thead tr:last-child th')
        const firstRowCells = document.querySelectorAll('tbody tr:first-child > td')
        const expansionCells = document.querySelectorAll('tbody tr.LemonTable__expansion > td')

        expect(headerCells).toHaveLength(1)
        expect(firstRowCells).toHaveLength(1)
        expect(firstRowCells[0]).toHaveTextContent('alpha')
        expect(expansionCells).toHaveLength(3)
        expect(expansionCells[0]).toHaveAttribute('colspan', '1')

        rerender(
            <LemonTable
                rowKey="id"
                dataSource={[]}
                columns={COLUMNS}
                expandable={{
                    expandedRowRender: () => <div>Expanded</div>,
                    showRowExpansionToggle: false,
                }}
            />
        )

        expect(document.querySelector('tbody tr.LemonTable__empty-state > td')).toHaveAttribute('colspan', '1')
    })

    it('keeps group headers aligned when the sticky first group has a single column', () => {
        // The sticky-first-group header is rendered as a title cell plus a filler cell. With one child
        // the filler's colSpan would be 0, which the DOM clamps to 1, adding a phantom column that
        // shifts every following group title one column to the right.
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                firstColumnSticky
                columns={[
                    { children: [{ title: 'Name', key: 'name', dataIndex: 'name' as keyof Row }] },
                    {
                        title: 'Metrics',
                        children: [
                            { title: 'Value', key: 'value', dataIndex: 'value' as keyof Row },
                            { title: 'Id', key: 'id', dataIndex: 'id' as keyof Row },
                        ],
                    },
                ]}
            />
        )
        const groupingRow = document.querySelector('tr.LemonTable__row--grouping')!
        const spannedColumns = Array.from(groupingRow.querySelectorAll('th')).reduce((sum, th) => sum + th.colSpan, 0)
        expect(spannedColumns).toBe(3)
    })

    describe('sticky header', () => {
        const renderWithWidths = (props: { stickyHeader?: boolean }, tableWidth: number, viewportWidth = 500): void => {
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (this: HTMLElement) {
                return this.tagName === 'TABLE' ? tableWidth : 0
            })
            jest.spyOn(Element.prototype, 'clientWidth', 'get').mockImplementation(function (this: Element) {
                return this.classList.contains('ScrollableShadows__inner') ? viewportWidth : 0
            })
            render(<LemonTable rowKey="id" dataSource={DATA} columns={COLUMNS} {...props} />)
        }

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('pins the header when the table fits its container', () => {
            renderWithWidths({ stickyHeader: true }, 400)
            expect(document.querySelector('.LemonTable')).toHaveClass('LemonTable--sticky-header')
        })

        it('keeps horizontal scrolling instead when the table is wider than its container', () => {
            renderWithWidths({ stickyHeader: true }, 800)
            expect(document.querySelector('.LemonTable')).not.toHaveClass('LemonTable--sticky-header')
        })

        it('switches between pinning and horizontal scrolling when the table or its container resizes', () => {
            const resizeCallbacks: (() => void)[] = []
            jest.spyOn(globalThis, 'ResizeObserver').mockImplementation((callback: ResizeObserverCallback) => {
                resizeCallbacks.push(() => callback([], {} as ResizeObserver))
                return { observe: () => null, unobserve: () => null, disconnect: () => null } as ResizeObserver
            })
            let tableWidth = 400
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (this: HTMLElement) {
                return this.tagName === 'TABLE' ? tableWidth : 0
            })
            jest.spyOn(Element.prototype, 'clientWidth', 'get').mockImplementation(function (this: Element) {
                return this.classList.contains('ScrollableShadows__inner') ? 500 : 0
            })
            render(<LemonTable rowKey="id" dataSource={DATA} columns={COLUMNS} stickyHeader />)
            const table = document.querySelector('.LemonTable')
            expect(table).toHaveClass('LemonTable--sticky-header')
            expect(resizeCallbacks.length).toBeGreaterThan(0)

            tableWidth = 800
            act(() => resizeCallbacks.forEach((callback) => callback()))
            expect(table).not.toHaveClass('LemonTable--sticky-header')

            tableWidth = 400
            act(() => resizeCallbacks.forEach((callback) => callback()))
            expect(table).toHaveClass('LemonTable--sticky-header')
        })

        it('does not pin the header by default', () => {
            renderWithWidths({}, 400)
            expect(document.querySelector('.LemonTable')).not.toHaveClass('LemonTable--sticky-header')
        })
    })
})
