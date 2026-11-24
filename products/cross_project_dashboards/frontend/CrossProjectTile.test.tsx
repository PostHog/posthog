import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { CrossProjectTile } from './CrossProjectTile'
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
    })

    it('renders the insight once its project answers', () => {
        render(
            <CrossProjectTile
                tile={tile()}
                result={{
                    insight: { name: 'Signups' } as any,
                    unavailable: null,
                }}
            />
        )

        expect(screen.getByText('Signups')).toBeInTheDocument()
    })

    it('gives the insight card the tile color, so a stored color is actually shown', () => {
        render(
            <CrossProjectTile
                tile={tile({ color: 'green' })}
                result={{
                    insight: { name: 'Signups' } as any,
                    unavailable: null,
                }}
            />
        )

        expect(screen.getByText('Signups')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="insight-card"]')).toHaveAttribute('data-ribbon', 'green')
    })

    it('tells the card which project the insight lives in, so its links open that project', () => {
        render(
            <CrossProjectTile
                tile={tile({ project_id: 54 })}
                result={{
                    insight: { name: 'Signups' } as any,
                    unavailable: null,
                }}
            />
        )

        expect(screen.getByText('Signups')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="insight-card"]')).toHaveAttribute('data-project', '54')
    })

    it.each([
        ['a loaded insight', { insight: { name: 'Signups' } as any, unavailable: null }, '[data-attr="insight-card"]'],
        [
            'an unavailable insight',
            { insight: null, unavailable: 'no-access' as const },
            '[data-attr="cross-project-tile-unavailable"]',
        ],
    ])('puts the grid class and handles on the card itself for %s', (_label, result, cardSelector) => {
        render(
            <CrossProjectTile tile={tile()} result={result} className="react-grid-item">
                <span data-attr="grid-resize-handle" />
            </CrossProjectTile>
        )

        expect(document.querySelector(cardSelector)).toBeInTheDocument()
        const card = document.querySelector(cardSelector)
        expect(card).toHaveClass('react-grid-item')
        expect(card?.querySelector('[data-attr="grid-resize-handle"]')).toBeInTheDocument()
    })

    it('renders an unavailable tile without a name when access is denied', () => {
        render(
            <CrossProjectTile
                tile={tile()}
                result={{
                    insight: null,
                    unavailable: 'no-access',
                }}
                projectName="Hedgebox EU"
            />
        )

        expect(screen.getByText(/do not have access/i)).toBeInTheDocument()
        expect(screen.queryByText('Signups')).not.toBeInTheDocument()
        expect(screen.queryByText('Hedgebox EU')).not.toBeInTheDocument()
    })

    it('renders an unavailable tile when the insight is gone', () => {
        render(
            <CrossProjectTile
                tile={tile()}
                result={{
                    insight: null,
                    unavailable: 'not-found',
                }}
            />
        )

        expect(screen.getByText(/no longer exists/i)).toBeInTheDocument()
    })

    it('keeps the insight on screen while it reloads', () => {
        render(
            <CrossProjectTile
                tile={tile()}
                result={{ insight: { name: 'Signups' } as any, unavailable: null }}
                loading
            />
        )

        expect(screen.getByText('Signups')).toBeInTheDocument()
    })
})
