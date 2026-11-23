import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { type WarehousePageTab, WarehousePageTabs } from './WarehousePageTabs'

const TABS: WarehousePageTab[] = [
    { value: 'activity', label: 'Activity', 'data-attr': 'tab-activity' },
    { value: 'performance', label: 'Performance', 'data-attr': 'tab-performance' },
]

function renderTabs(): void {
    render(
        <WarehousePageTabs tabs={TABS} page="queries">
            {(tab) => <div>body {tab}</div>}
        </WarehousePageTabs>
    )
}

describe('WarehousePageTabs', () => {
    afterEach(() => cleanup())

    beforeEach(() => {
        initKeaTests()
    })

    it('shows the tab named in the URL and keeps other parameters when going back to the first tab', () => {
        router.actions.replace('/warehouse/queries', { tab: 'performance', status: 'failed' })
        renderTabs()
        expect(screen.getByText('body performance')).toBeTruthy()

        fireEvent.click(screen.getByText('Activity'))

        expect(screen.getByText('body activity')).toBeTruthy()
        expect(router.values.searchParams).toEqual({ status: 'failed' })
    })

    it('adds the tab parameter for a later tab and ignores an unknown tab', () => {
        router.actions.replace('/warehouse/queries', { tab: 'nope' })
        renderTabs()
        expect(screen.getByText('body activity')).toBeTruthy()

        fireEvent.click(screen.getByText('Performance'))

        expect(router.values.searchParams).toEqual({ tab: 'performance' })
    })
})
