import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { METRICS } from '../homeFixtures'
import { KpiTileRow } from './KpiTileRow'

describe('KpiTileRow', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('renders one tile per server tile, with kebab-case data-attrs', () => {
        const metrics = { ...METRICS, tiles: METRICS.tiles.slice(0, 5) }
        const { container } = render(
            <KpiTileRow metrics={metrics} loading={false} links={{}} openChartKey={null} onToggleChart={() => {}} />
        )

        expect(
            Array.from(container.querySelectorAll('[data-attr^="home-tile-"]')).map((el) =>
                el.getAttribute('data-attr')
            )
        ).toEqual([
            'home-tile-cost',
            'home-tile-users',
            'home-tile-sessions',
            'home-tile-traces',
            'home-tile-error-rate',
        ])
    })

    it('shows skeleton tiles only while loading, and nothing for missing metrics', () => {
        const loading = render(
            <KpiTileRow metrics={null} loading links={{}} openChartKey={null} onToggleChart={() => {}} />
        )
        expect(loading.container.querySelector('.LemonSkeleton')).not.toBeNull()
        expect(loading.container.querySelector('[data-attr^="home-tile-"]')).toBeNull()
        loading.unmount()

        const missing = render(
            <KpiTileRow metrics={null} loading={false} links={{}} openChartKey={null} onToggleChart={() => {}} />
        )
        expect(missing.container.innerHTML).toBe('')
    })
})
