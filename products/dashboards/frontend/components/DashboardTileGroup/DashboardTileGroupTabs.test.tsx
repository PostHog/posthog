import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { DashboardTile } from '~/types'

import { type DashboardSection } from '../../dashboardTileSections'
import { DashboardTileGroupTabs } from './DashboardTileGroupTabs'

describe('DashboardTileGroupTabs', () => {
    afterEach(cleanup)

    it.each([
        { loading: true, hasTiles: false, expected: 'loading' },
        { loading: false, hasTiles: false, expected: 'empty' },
        { loading: true, hasTiles: true, expected: 'tiles' },
        { loading: false, hasTiles: true, expected: 'tiles' },
    ])('shows $expected when loading=$loading and hasTiles=$hasTiles', ({ loading, hasTiles, expected }) => {
        const section: DashboardSection = {
            kind: 'group',
            key: 'group-example',
            groupKey: 'example',
            group: { title: 'Example' },
            tiles: hasTiles ? [{ id: 1 } as DashboardTile] : [],
        }

        render(
            <DashboardTileGroupTabs
                sections={[section]}
                activeSectionKey={section.key}
                onSelect={() => {}}
                loading={loading}
            >
                <div>Tile content</div>
            </DashboardTileGroupTabs>
        )

        expect(screen.queryByLabelText('Loading dashboard tab') !== null).toBe(expected === 'loading')
        expect(screen.queryByText('Nothing to see here yet') !== null).toBe(expected === 'empty')
        expect(screen.queryByText('Tile content') !== null).toBe(expected === 'tiles')
        expect(screen.queryAllByRole('tab')).toHaveLength(loading ? 0 : 1)
        expect(screen.queryByLabelText('Loading dashboard tabs') !== null).toBe(loading)
    })
})
