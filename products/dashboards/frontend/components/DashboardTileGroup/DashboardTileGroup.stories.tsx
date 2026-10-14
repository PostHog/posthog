import type { Meta, StoryObj } from '@storybook/react'

import type { DashboardTileGroupApi } from '../../generated/api.schemas'
import { DashboardTileGroup } from './DashboardTileGroup'

const meta: Meta<typeof DashboardTileGroup> = {
    title: 'Products/Dashboards/Tiles/Tile group',
    component: DashboardTileGroup,
    parameters: { layout: 'padded' },
}
export default meta

const STYLES: { group: DashboardTileGroupApi; collapsed: boolean }[] = [
    { group: { title: 'Activation' }, collapsed: false },
    { group: { title: 'Revenue', rail: 'purple' }, collapsed: false },
    { group: { title: 'Retention', tint: false, rail: 'green' }, collapsed: false },
    { group: { title: 'Plain', tint: false }, collapsed: false },
    { group: { title: 'Collapsed', rail: 'orange' }, collapsed: true },
    { group: {}, collapsed: true },
]

function FakeTile(): JSX.Element {
    return <div className="h-20 rounded border bg-surface-primary" />
}

export const LongTitleInNarrowScene: StoryObj = {
    render: () => (
        <div className="w-[360px] bg-primary p-4">
            <DashboardTileGroup
                group={{
                    title: 'Weekly activation and retention for self-serve signups across every marketing channel',
                    rail: 'blue',
                }}
                tileCount={12}
                collapsed
                onToggle={() => {}}
                onPreload={() => {}}
            >
                <FakeTile />
            </DashboardTileGroup>
        </div>
    ),
}

export const Styles: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-4 bg-primary p-4">
            {STYLES.map(({ group, collapsed }, index) => (
                <DashboardTileGroup
                    key={index}
                    group={group}
                    tileCount={2}
                    collapsed={collapsed}
                    onToggle={() => {}}
                    onPreload={() => {}}
                >
                    <div className="grid grid-cols-2 gap-2">
                        <FakeTile />
                        <FakeTile />
                    </div>
                </DashboardTileGroup>
            ))}
        </div>
    ),
}
