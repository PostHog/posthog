import { fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { LemonTable } from './LemonTable'
import { LemonTableColumn } from './types'

interface TestRow {
    id: number
    name: string
}

const ROW_HEIGHT = 40
const VIEWPORT_HEIGHT = 600 // fits 15 rows of 40px
// Window (~15 rows) + overscan + partially visible rows — far below the 500-row dataset
const MAX_MOUNTED_ROWS = 40

const rows: TestRow[] = Array.from({ length: 500 }, (_, index) => ({ id: index, name: `row-marker-${index}` }))
const columns: LemonTableColumn<TestRow, keyof TestRow | undefined>[] = [
    { title: 'Name', key: 'name', render: (_, record) => record.name },
]

function mountedRowMarkers(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('tbody tr:not(.LemonTable__virtual-spacer)')).map(
        (row) => row.textContent ?? ''
    )
}

function renderTable(virtualized: boolean): HTMLElement {
    const { container } = render(
        <Provider>
            <LemonTable
                columns={columns}
                dataSource={rows}
                virtualized={virtualized}
                rowHeight={virtualized ? ROW_HEIGHT : undefined}
            />
        </Provider>
    )
    return container
}

describe('LemonTable', () => {
    beforeEach(() => {
        initKeaTests()
        // jsdom has no layout — the virtualizer sizes its window from the scroll container's offset dimensions
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(VIEWPORT_HEIGHT)
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('renders all rows by default', () => {
        const container = renderTable(false)

        expect(mountedRowMarkers(container)).toHaveLength(500)
    })

    it('mounts only the visible window of rows when virtualized', () => {
        const container = renderTable(true)

        const markers = mountedRowMarkers(container)
        expect(markers.length).toBeGreaterThan(0)
        expect(markers.length).toBeLessThan(MAX_MOUNTED_ROWS)
        expect(markers).toContain('row-marker-0')
        expect(markers).toContain('row-marker-10')
        expect(markers).not.toContain('row-marker-499')
    })

    it('moves the mounted window when the container scrolls', () => {
        const container = renderTable(true)
        const scroller = container.querySelector('.ScrollableShadows__inner')
        expect(scroller).not.toBeNull()

        fireEvent.scroll(scroller!, { target: { scrollTop: 300 * ROW_HEIGHT } })

        const markers = mountedRowMarkers(container)
        expect(markers.length).toBeLessThan(MAX_MOUNTED_ROWS)
        expect(markers).toContain('row-marker-300')
        expect(markers).toContain('row-marker-310')
        expect(markers).not.toContain('row-marker-0')
        expect(markers).not.toContain('row-marker-499')
    })
})
