import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { DashboardTextItem } from 'products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem'

import { DashboardButtonTileItem } from './DashboardButtonTileItem'
import { DashboardErrorTileItem } from './DashboardErrorTileItem'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: () => ({ push: jest.fn() }),
    useValues: () => ({ copyToDestinations: [] }),
}))
jest.mock('lib/components/RichContentEditor', () => ({ useRichContentEditor: () => null }))
jest.mock('scenes/insights/EmptyStates', () => ({ InsightErrorState: () => <div data-testid="error-state" /> }))

const commonProps = {
    className: 'ai-highlight-test',
    'data-dashboard-tile-id': '41',
    'data-dashboard-tile-highlighted': 'true',
    tabIndex: -1,
}

function assertRevealContract(element: Element, rendererClass: string): void {
    expect(element).toHaveClass('DashboardTileCard', rendererClass, 'ai-highlight-test')
    expect(element).toHaveAttribute('data-dashboard-tile-id', '41')
    expect(element).toHaveAttribute('data-dashboard-tile-highlighted', 'true')
    expect(element).toHaveAttribute('tabindex', '-1')
}

function tile(overrides: Partial<DashboardTile<QueryBasedInsightModel>>): DashboardTile<QueryBasedInsightModel> {
    return { id: 41, ...overrides } as DashboardTile<QueryBasedInsightModel>
}

describe('dashboard tile reveal props', () => {
    it.each([
        ['text', 'Plain text', 'text-card', 'TextCard'],
        ['image', '![Chart](https://example.test/chart.png)', 'image-tile', 'DashboardImageTile'],
    ] as const)('forwards the contract through the %s tile renderer', (_kind, body, dataAttr, rendererClass) => {
        const { container } = render(
            <DashboardTextItem
                tile={tile({ text: { id: 11, body } as DashboardTile<QueryBasedInsightModel>['text'] })}
                placement={DashboardPlacement.Dashboard}
                onEdit={jest.fn()}
                onDuplicate={jest.fn()}
                {...commonProps}
            />
        )

        const card = container.querySelector(`[data-attr="${dataAttr}"]`)
        expect(card).not.toBeNull()
        assertRevealContract(card!, rendererClass)
    })

    it('forwards the contract through the button tile renderer', () => {
        const { container } = render(
            <DashboardButtonTileItem
                tile={tile({
                    button_tile: { id: 12, text: 'Open', url: '/', style: 'primary' },
                } as Partial<DashboardTile<QueryBasedInsightModel>>)}
                placement={DashboardPlacement.Dashboard}
                onEdit={jest.fn()}
                onDuplicate={jest.fn()}
                {...commonProps}
            />
        )

        const card = container.querySelector('[data-attr="button-tile-card"]')
        expect(card).not.toBeNull()
        assertRevealContract(card!, 'ButtonTileCard')
    })

    it('forwards the contract through the error tile renderer', () => {
        const { container } = render(
            <DashboardErrorTileItem
                tile={tile({ error: { type: 'ValidationError', message: 'Invalid filters' } })}
                placement={DashboardPlacement.Dashboard}
                {...commonProps}
            />
        )

        const card = container.querySelector('[data-attr="dashboard-tile-error"]')
        expect(card).not.toBeNull()
        assertRevealContract(card!, 'InsightCard')
    })
})
