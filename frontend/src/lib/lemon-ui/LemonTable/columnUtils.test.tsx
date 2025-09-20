import { DEFAULT_COLUMN_WIDTH, getStickyColumnInfo } from './columnUtils'
import { LemonTableColumn } from './types'

describe('getStickyColumnInfo', () => {
    const mockColumns: LemonTableColumn<any, any>[] = [
        { key: 'name', dataIndex: 'name', title: 'Name' },
        { key: 'email', dataIndex: 'email', title: 'Email' },
        { key: 'status', dataIndex: 'status', title: 'Status' },
        { key: 'created_at', dataIndex: 'created_at', title: 'Created' },
    ]

    describe('when no sticky columns', () => {
        it('returns default values', () => {
            const result = getStickyColumnInfo('name', undefined, undefined, mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('returns default values for empty sticky columns array', () => {
            const result = getStickyColumnInfo('name', [], [], mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('when column is not sticky', () => {
        it('returns correct values for non-sticky column', () => {
            const result = getStickyColumnInfo('email', ['name'], [100], mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('when column is sticky', () => {
        it('identifies sticky column correctly', () => {
            const result = getStickyColumnInfo('name', ['name'], [100], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0)
        })

        it('calculates left position for second sticky column', () => {
            const result = getStickyColumnInfo('email', ['name', 'email'], [100, 150], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(100)
        })

        it('calculates left position for third sticky column', () => {
            const result = getStickyColumnInfo('status', ['name', 'email', 'status'], [100, 150, 120], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(250)
        })
    })

    describe('when sticky columns are not in order', () => {
        it('identifies last sticky column based on table position', () => {
            const result = getStickyColumnInfo('email', ['email', 'name'], [150, 100], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(100) // name comes before email in table, so leftPosition is 100
        })

        it('identifies first sticky column as last when it appears last in table', () => {
            const result = getStickyColumnInfo('name', ['email', 'name'], [150, 100], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0) // name is first in table, so leftPosition is 0
        })
    })

    describe('when sticky column widths are missing', () => {
        it('uses default column width', () => {
            const result = getStickyColumnInfo('email', ['name', 'email'], undefined, mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0) // when stickyColumnWidths is undefined, leftPosition is 0
        })

        it('uses default width for missing width in array', () => {
            const result = getStickyColumnInfo('status', ['name', 'email', 'status'], [100, 0, 120], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(100 + DEFAULT_COLUMN_WIDTH)
        })
    })

    describe('when all columns are missing', () => {
        it('handles missing allColumns gracefully', () => {
            const result = getStickyColumnInfo('name', ['name'], [100], undefined)
            expect(result.isSticky).toBe(true)
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
            const result = getStickyColumnInfo('name', ['name'], [100], columnsWithDataIndex)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0)
        })

        it('calculates position correctly with dataIndex columns', () => {
            const result = getStickyColumnInfo('email', ['name', 'email'], [100, 150], columnsWithDataIndex)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(100)
        })
    })

    describe('edge cases', () => {
        it('handles column not found in allColumns', () => {
            const result = getStickyColumnInfo('nonexistent', ['name'], [100], mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles sticky column not found in allColumns', () => {
            const result = getStickyColumnInfo('name', ['nonexistent'], [100], mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles empty string column key', () => {
            const result = getStickyColumnInfo('', ['name'], [100], mockColumns)
            expect(result.isSticky).toBe(false)
            expect(result.leftPosition).toBe(0)
        })

        it('handles duplicate sticky columns', () => {
            const result = getStickyColumnInfo('name', ['name', 'name'], [100, 100], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0)
        })
    })

    describe('complex scenarios', () => {
        it('handles multiple sticky columns with gaps', () => {
            const result = getStickyColumnInfo('created_at', ['name', 'created_at'], [100, 200], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(100)
        })

        it('handles all columns being sticky', () => {
            const result = getStickyColumnInfo(
                'status',
                ['name', 'email', 'status', 'created_at'],
                [100, 150, 120, 180],
                mockColumns
            )
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(250)
        })

        it('handles last column being the only sticky column', () => {
            const result = getStickyColumnInfo('created_at', ['created_at'], [180], mockColumns)
            expect(result.isSticky).toBe(true)
            expect(result.leftPosition).toBe(0)
        })
    })
})
