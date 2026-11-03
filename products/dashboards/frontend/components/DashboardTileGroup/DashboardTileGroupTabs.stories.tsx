import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { useStorybookMocks } from '~/mocks/browser'
import type { DashboardBasicType } from '~/types'

import { type DashboardSection, UNGROUPED_TILES_TAB_KEY } from '../../dashboardTileSections'
import { DashboardTileGroupTabs } from './DashboardTileGroupTabs'

const meta: Meta<typeof DashboardTileGroupTabs> = {
    title: 'Products/Dashboards/Tiles/Tile group tabs',
    component: DashboardTileGroupTabs,
    parameters: { layout: 'padded' },
}
export default meta

const SECTIONS: DashboardSection[] = [
    { kind: 'tiles', key: UNGROUPED_TILES_TAB_KEY, tiles: [] },
    { kind: 'group', key: 'group-activation', groupKey: 'activation', group: { title: 'Activation' }, tiles: [] },
    {
        kind: 'group',
        key: 'group-revenue',
        groupKey: 'revenue',
        group: { title: 'Revenue', color: 'purple' },
        tiles: [],
    },
]

function TabsWithMenu({ activeSectionKey }: { activeSectionKey: string }): JSX.Element {
    useStorybookMocks({ get: { '/api/projects/:team_id/dashboards/': { count: 0, results: [] } } })
    return (
        <div className="h-60 w-[640px] bg-primary p-4">
            <DashboardTileGroupTabs
                sections={SECTIONS}
                activeSectionKey={activeSectionKey}
                onSelect={() => {}}
                copyToDestinations={[{ dashboard: { id: 42, name: 'Example dashboard' } as DashboardBasicType }]}
                onCopyGroupToDashboard={() => {}}
                onChangeGroupDisplay={() => {}}
            >
                <div className="h-20 rounded border bg-surface-primary" />
            </DashboardTileGroupTabs>
        </div>
    )
}

async function openGroupMenu(): Promise<void> {
    const trigger = await waitFor(() => {
        const element = document.querySelector<HTMLElement>('[data-attr="dashboard-tile-group-menu"]')
        if (!element) {
            throw new Error('Group menu trigger not found')
        }
        return element
    })
    trigger.click()
}

export const GroupTabMenuOpen: StoryObj = {
    render: () => <TabsWithMenu activeSectionKey="group-revenue" />,
    play: openGroupMenu,
}

export const OverviewTabMenuOpen: StoryObj = {
    render: () => <TabsWithMenu activeSectionKey={UNGROUPED_TILES_TAB_KEY} />,
    play: openGroupMenu,
}
