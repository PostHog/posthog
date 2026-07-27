import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { OverviewGrid, OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'

import { accountsOverviewTilesLogic, AccountsOverviewTile, isTileClickable } from './accountsOverviewTilesLogic'

function tileCaption(tile: AccountsOverviewTile): string | undefined {
    const { metric } = tile
    switch (metric.type) {
        case 'count':
            return undefined
        case 'sum':
            return `sum of ${metric.columnLabel}`
        case 'avg':
            return `avg of ${metric.columnLabel}`
        case 'count_threshold':
            return `${metric.columnLabel} ${metric.operator} ${metric.value}`
    }
}

function tileLabelByKey(tiles: AccountsOverviewTile[]): (key: string) => string {
    const labelsById = new Map(tiles.map((tile) => [tile.id, tile.label]))
    return (key) => labelsById.get(key) ?? key
}

export function AccountsOverviewTiles(): JSX.Element {
    const { reconciledTiles, tileValues, tilesLoading, selectedTileId } = useValues(accountsOverviewTilesLogic)
    const { showEditor, toggleTileSelection } = useActions(accountsOverviewTilesLogic)

    const overviewItems: OverviewItem[] = reconciledTiles.map((tile) => ({
        key: tile.id,
        value: tileValues[tile.id] ?? undefined,
        kind: 'unit',
        caption: tileCaption(tile),
        selected: selectedTileId === tile.id,
        onClick: isTileClickable(tile) ? () => toggleTileSelection(tile) : undefined,
    }))

    if (reconciledTiles.length === 0) {
        return (
            <div
                className="border rounded p-6 flex flex-col items-center justify-center gap-2 text-secondary bg-surface-primary"
                data-attr="accounts-overview-tiles"
            >
                <span>No overview tiles configured.</span>
                <LemonButton type="primary" size="small" onClick={showEditor}>
                    Add tile
                </LemonButton>
            </div>
        )
    }

    return (
        <div data-attr="accounts-overview-tiles">
            <OverviewGrid
                items={overviewItems}
                loading={tilesLoading}
                numSkeletons={Math.max(reconciledTiles.length, 1)}
                labelFromKey={tileLabelByKey(reconciledTiles)}
            />
        </div>
    )
}
