import { Meta } from '@storybook/react'

import { ChartTileSkeleton, TableTileSkeleton, WorldMapTileSkeleton } from './index'

const meta: Meta = {
    title: 'Web Analytics/Tile Skeletons',
    parameters: {
        layout: 'padded',
        testOptions: {
            waitForLoadersToDisappear: false,
        },
        docs: {
            description: {
                component:
                    'Content-shaped loading skeletons used inside the web analytics dashboard while each tile fetches its data. ' +
                    'They render in place of the inner `<Query>` when `responseLoading && !response` — filter refetches keep ' +
                    'the previous data visible instead.',
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

function TileChrome({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1 w-160">{children}</div>
}

export function Table(): JSX.Element {
    return (
        <TileChrome>
            <TableTileSkeleton />
        </TileChrome>
    )
}

export function TableTwoNumericColumns(): JSX.Element {
    return (
        <TileChrome>
            <TableTileSkeleton numericColumns={2} />
        </TileChrome>
    )
}

export function Chart(): JSX.Element {
    return (
        <TileChrome>
            <ChartTileSkeleton />
        </TileChrome>
    )
}

export function ChartWithoutLegend(): JSX.Element {
    return (
        <TileChrome>
            <ChartTileSkeleton showLegendStrip={false} />
        </TileChrome>
    )
}

export function WorldMap(): JSX.Element {
    return (
        <TileChrome>
            <WorldMapTileSkeleton />
        </TileChrome>
    )
}
