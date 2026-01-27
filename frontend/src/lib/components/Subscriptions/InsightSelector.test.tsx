import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { DashboardTile } from '~/types'

import { InsightSelector } from './InsightSelector'
import { MAX_INSIGHTS } from './insightSelectorLogic'

function renderInsightSelector(props: {
    tiles: DashboardTile[]
    selectedInsightIds: number[]
    onChange: jest.Mock
    onDefaultsApplied?: jest.Mock
}): ReturnType<typeof render> {
    return render(
        <Provider>
            <InsightSelector {...props} />
        </Provider>
    )
}

const createMockTiles = (): Partial<DashboardTile>[] => [
    { id: 1, insight: { id: 101, name: 'Pageviews' } as any, layouts: { sm: { x: 0, y: 0, w: 1, h: 1 } } },
    { id: 2, insight: { id: 102, name: 'Sessions' } as any, layouts: { sm: { x: 0, y: 1, w: 1, h: 1 } } },
    { id: 3, insight: { id: 103, name: 'Users' } as any, layouts: { sm: { x: 0, y: 2, w: 1, h: 1 } } },
]

describe('InsightSelector', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders insight checkboxes with correct selection state', () => {
        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101],
            onChange: jest.fn(),
        })

        expect(screen.getByText('Pageviews')).toBeInTheDocument()
        expect(screen.getByText('Sessions')).toBeInTheDocument()
        expect(screen.getByText('Users')).toBeInTheDocument()

        // Verify checkbox states - only Pageviews (101) should be checked
        const checkboxes = screen.getAllByRole('checkbox')
        expect(checkboxes).toHaveLength(3)
        expect(checkboxes[0]).toBeChecked() // Pageviews (101)
        expect(checkboxes[1]).not.toBeChecked() // Sessions (102)
        expect(checkboxes[2]).not.toBeChecked() // Users (103)
    })

    it('shows selection count', () => {
        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101, 102],
            onChange: jest.fn(),
        })

        expect(screen.getByText(`2 of ${MAX_INSIGHTS} insights selected`)).toBeInTheDocument()
    })

    it('calls onChange when selecting an insight', async () => {
        const onChange = jest.fn()
        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101],
            onChange,
        })

        await userEvent.click(screen.getByText('Sessions'))
        expect(onChange).toHaveBeenCalledWith([101, 102])
    })

    it('calls onChange when deselecting an insight', async () => {
        const onChange = jest.fn()
        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101, 102],
            onChange,
        })

        await userEvent.click(screen.getByText('Pageviews'))
        expect(onChange).toHaveBeenCalledWith([102])
    })

    it('auto-selects first N insights when empty and calls onDefaultsApplied', () => {
        const onChange = jest.fn()
        const onDefaultsApplied = jest.fn()

        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [],
            onChange,
            onDefaultsApplied,
        })

        expect(onChange).toHaveBeenCalledWith([101, 102, 103])
        expect(onDefaultsApplied).toHaveBeenCalledWith([101, 102, 103])
    })

    it('filters out stale IDs that no longer exist in tiles', () => {
        const onChange = jest.fn()

        // Selected IDs include 999 which doesn't exist in tiles
        renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101, 999, 102],
            onChange,
        })

        // Should call onChange to remove the stale ID
        expect(onChange).toHaveBeenCalledWith([101, 102])
    })

    it('shows max limit message when at capacity', () => {
        const sixInsightTiles = Array.from({ length: 6 }, (_, i) => ({
            id: i + 1,
            insight: { id: 100 + i, name: `Insight ${i}` } as any,
            layouts: { sm: { x: 0, y: i, w: 1, h: 1 } },
        }))
        const selectedIds = sixInsightTiles.map((t) => t.insight.id)

        renderInsightSelector({
            tiles: sixInsightTiles as DashboardTile[],
            selectedInsightIds: selectedIds,
            onChange: jest.fn(),
        })

        expect(screen.getByText(`Maximum ${MAX_INSIGHTS} insights. Deselect one to add another.`)).toBeInTheDocument()
    })

    it('shows warning when none selected after user interaction', async () => {
        const onChange = jest.fn()

        // Start with one selected so auto-select doesn't trigger
        const { rerender } = renderInsightSelector({
            tiles: createMockTiles() as DashboardTile[],
            selectedInsightIds: [101],
            onChange,
        })

        // Click to deselect and mark user as having interacted
        await userEvent.click(screen.getByText('Pageviews'))

        // Rerender with empty selection - need to wrap in Provider again
        rerender(
            <Provider>
                <InsightSelector
                    tiles={createMockTiles() as DashboardTile[]}
                    selectedInsightIds={[]}
                    onChange={onChange}
                />
            </Provider>
        )

        expect(screen.getByText('Select at least one insight')).toBeInTheDocument()
    })

    it('shows empty state when no insights in dashboard', () => {
        renderInsightSelector({
            tiles: [],
            selectedInsightIds: [],
            onChange: jest.fn(),
        })

        expect(screen.getByText('No insights found in this dashboard.')).toBeInTheDocument()
    })

    it('uses derived_name when name is not available', () => {
        const tilesWithDerivedName: Partial<DashboardTile>[] = [
            {
                id: 1,
                insight: { id: 101, derived_name: 'Derived Insight Name' } as any,
                layouts: { sm: { x: 0, y: 0, w: 1, h: 1 } },
            },
        ]

        renderInsightSelector({
            tiles: tilesWithDerivedName as DashboardTile[],
            selectedInsightIds: [101],
            onChange: jest.fn(),
        })

        expect(screen.getByText('Derived Insight Name')).toBeInTheDocument()
    })

    it('shows "Untitled insight" when no name available', () => {
        const tilesWithoutName: Partial<DashboardTile>[] = [
            { id: 1, insight: { id: 101 } as any, layouts: { sm: { x: 0, y: 0, w: 1, h: 1 } } },
        ]

        renderInsightSelector({
            tiles: tilesWithoutName as DashboardTile[],
            selectedInsightIds: [101],
            onChange: jest.fn(),
        })

        expect(screen.getByText('Untitled insight')).toBeInTheDocument()
    })

    it('filters insights by search when more than 10 tiles', async () => {
        const manyTiles = Array.from({ length: 11 }, (_, i) => ({
            id: i + 1,
            insight: { id: 100 + i, name: i === 0 ? 'Special Insight' : `Insight ${i}` } as any,
            layouts: { sm: { x: 0, y: i, w: 1, h: 1 } },
        }))

        renderInsightSelector({
            tiles: manyTiles as DashboardTile[],
            selectedInsightIds: [100],
            onChange: jest.fn(),
        })

        const searchInput = screen.getByPlaceholderText('Search insights...')
        await userEvent.type(searchInput, 'Special')

        // Should only show the matching insight
        expect(screen.getByText('Special Insight')).toBeInTheDocument()
        expect(screen.queryByText('Insight 1')).not.toBeInTheDocument()
    })

    it('shows no match message when search returns empty', async () => {
        const manyTiles = Array.from({ length: 11 }, (_, i) => ({
            id: i + 1,
            insight: { id: 100 + i, name: `Insight ${i}` } as any,
            layouts: { sm: { x: 0, y: i, w: 1, h: 1 } },
        }))

        renderInsightSelector({
            tiles: manyTiles as DashboardTile[],
            selectedInsightIds: [100],
            onChange: jest.fn(),
        })

        const searchInput = screen.getByPlaceholderText('Search insights...')
        await userEvent.type(searchInput, 'nonexistent')

        expect(screen.getByText('No insights match your search.')).toBeInTheDocument()
    })
})
