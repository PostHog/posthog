import {
    DEFAULT_SIDEBAR_CARD_LAYOUT,
    moveSidebarRow,
    normalizeSidebarLayout,
    SidebarCardLayout,
    toggleSidebarRow,
} from './ticketSidebarLayout'

describe('ticketSidebarLayout', () => {
    describe('normalizeSidebarLayout', () => {
        it('returns default layout when input is not an array', () => {
            expect(normalizeSidebarLayout(null)).toEqual(DEFAULT_SIDEBAR_CARD_LAYOUT)
            expect(normalizeSidebarLayout(undefined)).toEqual(DEFAULT_SIDEBAR_CARD_LAYOUT)
            expect(normalizeSidebarLayout('invalid')).toEqual(DEFAULT_SIDEBAR_CARD_LAYOUT)
            expect(normalizeSidebarLayout(123)).toEqual(DEFAULT_SIDEBAR_CARD_LAYOUT)
        })

        it('appends missing rows to a partial layout', () => {
            const partial = [
                { id: 'status', visible: true },
                { id: 'priority', visible: false },
            ]
            const normalized = normalizeSidebarLayout(partial)

            expect(normalized[0]).toEqual({ id: 'status', visible: true })
            expect(normalized[1]).toEqual({ id: 'priority', visible: false })
            expect(normalized.length).toBe(DEFAULT_SIDEBAR_CARD_LAYOUT.length)

            // Missing rows should be appended in their default order and visibility
            const missingRows = normalized.slice(2)
            expect(missingRows.map((r) => r.id)).not.toContain('status')
            expect(missingRows.map((r) => r.id)).not.toContain('priority')
            expect(missingRows.find((r) => r.id === 'customer')?.visible).toBe(true)
        })

        it('discards invalid row IDs and deduplicates identical IDs', () => {
            const messy = [
                { id: 'non_existent_row', visible: true },
                { id: 'status', visible: true },
                { id: 'status', visible: false }, // Duplicate
                null,
                'not an object',
                { id: 'assignee', visible: false },
            ]
            const normalized = normalizeSidebarLayout(messy)

            expect(normalized.find((r) => r.id === ('non_existent_row' as any))).toBeUndefined()
            const statusRows = normalized.filter((r) => r.id === 'status')
            expect(statusRows).toHaveLength(1)
            expect(statusRows[0].visible).toBe(true)
            expect(normalized.find((r) => r.id === 'assignee')?.visible).toBe(false)
        })
    })

    describe('moveSidebarRow', () => {
        const sampleLayout: SidebarCardLayout = [
            { id: 'customer', visible: true },
            { id: 'created', visible: true },
            { id: 'updated', visible: true },
            { id: 'status', visible: true },
        ]

        it('moves row forward', () => {
            const moved = moveSidebarRow(sampleLayout, 0, 2)
            expect(moved.map((r) => r.id)).toEqual(['created', 'updated', 'customer', 'status'])
        })

        it('moves row backward', () => {
            const moved = moveSidebarRow(sampleLayout, 3, 1)
            expect(moved.map((r) => r.id)).toEqual(['customer', 'status', 'created', 'updated'])
        })

        it('returns unchanged layout for invalid indices', () => {
            expect(moveSidebarRow(sampleLayout, -1, 2)).toEqual(sampleLayout)
            expect(moveSidebarRow(sampleLayout, 0, 10)).toEqual(sampleLayout)
            expect(moveSidebarRow(sampleLayout, 1, 1)).toEqual(sampleLayout)
        })
    })

    describe('toggleSidebarRow', () => {
        const sampleLayout: SidebarCardLayout = [
            { id: 'status', visible: true },
            { id: 'priority', visible: false },
        ]

        it('toggles visibility from true to false', () => {
            const updated = toggleSidebarRow(sampleLayout, 'status')
            expect(updated.find((r) => r.id === 'status')?.visible).toBe(false)
        })

        it('toggles visibility from false to true', () => {
            const updated = toggleSidebarRow(sampleLayout, 'priority')
            expect(updated.find((r) => r.id === 'priority')?.visible).toBe(true)
        })
    })
})
