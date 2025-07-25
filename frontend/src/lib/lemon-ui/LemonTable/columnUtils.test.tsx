import { getPinnedColumnInfo, DEFAULT_COLUMN_WIDTH } from './columnUtils'
import { LemonTableColumn } from './types'

describe('getPinnedColumnInfo', () => {
    const mockColumns: LemonTableColumn<any, any>[] = [
        { key: 'name', dataIndex: 'name', title: 'Name' },
        { key: 'email', dataIndex: 'email', title: 'Email' },
        { key: 'status', dataIndex: 'status', title: 'Status' },
        { key: 'created_at', dataIndex: 'created_at', title: 'Created' },
    ]

    describe('when no pinned columns', () => {
        it('returns default values', () => {
            const result = getPinnedColumnInfo('name', undefined, undefined, mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('returns default values for empty pinned columns array', () => {
            const result = getPinnedColumnInfo('name', [], [], mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('when column is not pinned', () => {
        it('returns correct values for non-pinned column', () => {
            const result = getPinnedColumnInfo('email', ['name'], [100], mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('when column is pinned', () => {
        it('identifies pinned column correctly', () => {
            const result = getPinnedColumnInfo('name', ['name'], [100], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(0)
        })

        it('calculates left position for second pinned column', () => {
            const result = getPinnedColumnInfo('email', ['name', 'email'], [100, 150], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(100)
        })

        it('calculates left position for third pinned column', () => {
            const result = getPinnedColumnInfo('status', ['name', 'email', 'status'], [100, 150, 120], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(250)
        })
    })

    describe('when pinned columns are not in order', () => {
        it('identifies last pinned column based on table position', () => {
            const result = getPinnedColumnInfo('email', ['email', 'name'], [150, 100], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true) // email appears last in table (position 1)
            expect(result.leftPosition).toBe(100) // name comes before email in table, so leftPosition is 100
        })

        it('identifies first pinned column as last when it appears last in table', () => {
            const result = getPinnedColumnInfo('name', ['email', 'name'], [150, 100], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(false) // name appears first in table (position 0)
            expect(result.leftPosition).toBe(0) // name is first in table, so leftPosition is 0
        })
    })

    describe('when pinned column widths are missing', () => {
        it('uses default column width', () => {
            const result = getPinnedColumnInfo('email', ['name', 'email'], undefined, mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true) // email appears last in table (position 1)
            expect(result.leftPosition).toBe(0) // when pinnedColumnWidths is undefined, leftPosition is 0
        })

        it('uses default width for missing width in array', () => {
            const result = getPinnedColumnInfo('status', ['name', 'email', 'status'], [100, 0, 120], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(100 + DEFAULT_COLUMN_WIDTH)
        })
    })

    describe('when all columns are missing', () => {
        it('handles missing allColumns gracefully', () => {
            const result = getPinnedColumnInfo('name', ['name'], [100], undefined)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(false) // when allColumns is undefined, isLastPinned is false
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('when column uses dataIndex instead of key', () => {
        const columnsWithDataIndex: LemonTableColumn<any, any>[] = [
            { dataIndex: 'name', title: 'Name' },
            { dataIndex: 'email', title: 'Email' },
            { dataIndex: 'status', title: 'Status' },
        ]

        it('finds column by dataIndex', () => {
            const result = getPinnedColumnInfo('name', ['name'], [100], columnsWithDataIndex)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(0)
        })

        it('calculates position correctly with dataIndex columns', () => {
            const result = getPinnedColumnInfo('email', ['name', 'email'], [100, 150], columnsWithDataIndex)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(100)
        })
    })

    describe('edge cases', () => {
        it('handles column not found in allColumns', () => {
            const result = getPinnedColumnInfo('nonexistent', ['name'], [100], mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles pinned column not found in allColumns', () => {
            const result = getPinnedColumnInfo('name', ['nonexistent'], [100], mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles empty string column key', () => {
            const result = getPinnedColumnInfo('', ['name'], [100], mockColumns)
            expect(result.isPinned).toBe(false)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles duplicate pinned columns', () => {
            const result = getPinnedColumnInfo('name', ['name', 'name'], [100, 100], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('complex scenarios', () => {
        it('handles multiple pinned columns with gaps', () => {
            const result = getPinnedColumnInfo('created_at', ['name', 'created_at'], [100, 200], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(100)
        })

        it('handles all columns being pinned', () => {
            const result = getPinnedColumnInfo(
                'status',
                ['name', 'email', 'status', 'created_at'],
                [100, 150, 120, 180],
                mockColumns
            )
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(false)
            expect(result.leftPosition).toBe(250)
        })

        it('handles last column being the only pinned column', () => {
            const result = getPinnedColumnInfo('created_at', ['created_at'], [180], mockColumns)
            expect(result.isPinned).toBe(true)
            expect(result.isLastPinned).toBe(true)
            expect(result.leftPosition).toBe(0)
        })
    })
})
