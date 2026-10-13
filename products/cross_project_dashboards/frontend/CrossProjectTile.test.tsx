import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { CrossProjectTile } from './CrossProjectTile'
import * as tileFetch from './crossProjectTileFetch'
import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

jest.mock('lib/components/Cards/InsightCard/InsightCard', () => ({
    InsightCard: ({
        insight,
        ribbonColor,
        projectId,
        className,
        children,
    }: {
        insight: { name: string }
        ribbonColor?: string | null
        projectId?: number
        className?: string
        children?: React.ReactNode
    }) => (
        <div
            data-attr="insight-card"
            data-ribbon={ribbonColor ?? 'none'}
            data-project={projectId ?? 'none'}
            className={className}
        >
            {insight.name}
            {children}
        </div>
    ),
}))

const tile = (overrides: Partial<CrossProjectDashboardTileApi> = {}): CrossProjectDashboardTileApi =>
    ({
        id: 'tile-1',
        project_id: 42,
        insight_id: 7,
        layouts: {},
        color: null,
        filters_overrides: {},
        ...overrides,
    }) as CrossProjectDashboardTileApi

describe('CrossProjectTile', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('renders the insight once its project answers', async () => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue({
            insight: { name: 'Signups' } as any,
            unavailable: null,
        })

        render(<CrossProjectTile tile={tile()} />)

        await waitFor(() => expect(screen.getByText('Signups')).toBeInTheDocument())
    })

    it('gives the insight card the tile color, so a stored color is actually shown', async () => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue({
            insight: { name: 'Signups' } as any,
            unavailable: null,
        })

        render(<CrossProjectTile tile={tile({ color: 'green' })} />)

        await waitFor(() => expect(screen.getByText('Signups')).toBeInTheDocument())
        expect(document.querySelector('[data-attr="insight-card"]')).toHaveAttribute('data-ribbon', 'green')
    })

    it('tells the card which project the insight lives in, so its links open that project', async () => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue({
            insight: { name: 'Signups' } as any,
            unavailable: null,
        })

        render(<CrossProjectTile tile={tile({ project_id: 54 })} />)

        await waitFor(() => expect(screen.getByText('Signups')).toBeInTheDocument())
        expect(document.querySelector('[data-attr="insight-card"]')).toHaveAttribute('data-project', '54')
    })

    it.each([
        ['a loaded insight', { insight: { name: 'Signups' } as any, unavailable: null }, '[data-attr="insight-card"]'],
        [
            'an unavailable insight',
            { insight: null, unavailable: 'no-access' as const },
            '[data-attr="cross-project-tile-unavailable"]',
        ],
    ])('puts the grid class and handles on the card itself for %s', async (_label, result, cardSelector) => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue(result)

        render(
            <CrossProjectTile tile={tile()} className="react-grid-item">
                <span data-attr="grid-resize-handle" />
            </CrossProjectTile>
        )

        await waitFor(() => expect(document.querySelector(cardSelector)).toBeInTheDocument())
        const card = document.querySelector(cardSelector)
        expect(card).toHaveClass('react-grid-item')
        expect(card?.querySelector('[data-attr="grid-resize-handle"]')).toBeInTheDocument()
    })

    it('renders an unavailable tile without a name when access is denied', async () => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue({
            insight: null,
            unavailable: 'no-access',
        })

        render(<CrossProjectTile tile={tile()} projectName="Hedgebox EU" />)

        await waitFor(() => expect(screen.getByText(/do not have access/i)).toBeInTheDocument())
        expect(screen.queryByText('Signups')).not.toBeInTheDocument()
        expect(screen.queryByText('Hedgebox EU')).not.toBeInTheDocument()
    })

    it('renders an unavailable tile when the insight is gone', async () => {
        jest.spyOn(tileFetch, 'fetchCrossProjectTile').mockResolvedValue({
            insight: null,
            unavailable: 'not-found',
        })

        render(<CrossProjectTile tile={tile()} />)

        await waitFor(() => expect(screen.getByText(/no longer exists/i)).toBeInTheDocument())
    })

    it('fetches from the tile own project, with the tile override over the dashboard filters', async () => {
        const spy = jest
            .spyOn(tileFetch, 'fetchCrossProjectTile')
            .mockResolvedValue({ insight: { name: 'X' } as any, unavailable: null })

        render(
            <CrossProjectTile
                tile={tile({ project_id: 99, insight_id: 3, filters_overrides: { date_from: '-7d' } })}
                dashboardFilters={{ date_from: '-30d', interval: 'week' }}
            />
        )

        await waitFor(() => expect(spy).toHaveBeenCalledWith(99, 3, { date_from: '-7d', interval: 'week' }))
    })
})
