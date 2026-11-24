import { cleanup, fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import {
    TraceMetricChangeToneApi,
    TraceMetricChangeUnitApi,
    TraceMetricKeyApi,
    TraceMetricStatusApi,
    type TraceMetricTileApi,
} from '../../../generated/api.schemas'
import { KpiTile } from './KpiTile'

const DOCS_URL = 'https://posthog.com/docs/ai-observability/sessions'

function tileOf(overrides: Partial<TraceMetricTileApi>): TraceMetricTileApi {
    return {
        key: TraceMetricKeyApi.Cost,
        label: 'Cost',
        value: 1204,
        previous: 1075,
        change: 12,
        changeUnit: TraceMetricChangeUnitApi.Percent,
        changeTone: TraceMetricChangeToneApi.Neutral,
        status: TraceMetricStatusApi.Ok,
        docsUrl: null,
        setupLabel: null,
        detail: 'Spend across all models',
        latencyQuantiles: null,
        series: [1, 2, 3],
        insightQuery: 'SELECT 1',
        ...overrides,
    }
}

function shownNumbers(container: HTMLElement, attr: string): string[] {
    return Array.from(container.querySelectorAll(`[data-attr="${attr}"] [translate="no"]`)).map(
        (element) => element.textContent ?? ''
    )
}

describe('KpiTile', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('shows Not set up and links its setup label to the docs in a new tab', () => {
        const { container } = render(
            <KpiTile
                tile={tileOf({
                    key: TraceMetricKeyApi.Sessions,
                    label: 'Sessions',
                    value: null,
                    change: null,
                    status: TraceMetricStatusApi.NotSetUp,
                    docsUrl: DOCS_URL,
                    setupLabel: 'Add session IDs',
                })}
            />
        )

        const link = container.querySelector('[data-attr="home-tile-sessions-not-set-up"]')
        expect(container.textContent).toContain('Not set up')
        expect(link?.textContent).toBe('Add session IDs')
        expect(link?.getAttribute('href')).toBe(DOCS_URL)
        expect(link?.getAttribute('target')).toBe('_blank')
    })

    it.each<[string, Partial<TraceMetricTileApi>, string[]]>([
        ['percent', {}, ['$1,204.00', '+12%']],
        [
            'points',
            {
                key: TraceMetricKeyApi.ErrorRate,
                value: 0.018,
                change: -0.43,
                changeUnit: TraceMetricChangeUnitApi.Points,
            },
            ['1.8%', '−0.4pp'],
        ],
        ['no previous period', { change: null }, ['$1,204.00']],
    ])('formats value and change by unit: %s', (_name, overrides, shown) => {
        const tile = tileOf(overrides)
        const { container } = render(<KpiTile tile={tile} />)

        expect(shownNumbers(container, `home-tile-${tile.key.replaceAll('_', '-')}`)).toEqual(shown)
    })

    it('toggles its chart from a button that shows whether the chart is open', () => {
        const onToggleChart = jest.fn()
        const { container, rerender } = render(<KpiTile tile={tileOf({})} onToggleChart={onToggleChart} />)
        const button = (): Element | null => container.querySelector('[data-attr="home-chart-cost-toggle"]')

        expect(button()?.getAttribute('aria-pressed')).toBe('false')
        fireEvent.click(button()!)
        rerender(<KpiTile tile={tileOf({})} onToggleChart={onToggleChart} chartOpen />)

        expect(onToggleChart).toHaveBeenCalledTimes(1)
        expect(button()?.getAttribute('aria-pressed')).toBe('true')
    })

    it('has no chart button when the tile is not set up', () => {
        const { container } = render(
            <KpiTile tile={tileOf({ status: TraceMetricStatusApi.NotSetUp })} onToggleChart={() => {}} />
        )

        expect(container.querySelector('[data-attr="home-chart-cost-toggle"]')).toBeNull()
    })

    it.each([
        [TraceMetricChangeToneApi.Good, 'LemonTag--success'],
        [TraceMetricChangeToneApi.Bad, 'LemonTag--danger'],
        [TraceMetricChangeToneApi.Neutral, 'LemonTag--muted'],
    ])('colors a %s change as %s', (changeTone, tagClass) => {
        const { container } = render(<KpiTile tile={tileOf({ changeTone })} />)

        expect(container.querySelector('.LemonTag')?.classList).toContain(tagClass)
    })
})
