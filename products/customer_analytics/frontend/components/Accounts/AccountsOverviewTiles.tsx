import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { OverviewGrid, OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'

import { AccountsOverviewTilesEditor } from './AccountsOverviewTilesEditor'
import { accountsOverviewTilesLogic, AccountsOverviewTile } from './accountsOverviewTilesLogic'

function tileToOverviewItem(tile: AccountsOverviewTile, value: number | null): OverviewItem {
    return {
        key: tile.id,
        value: value ?? undefined,
        kind: 'unit',
    }
}

function tileLabelByKey(tiles: AccountsOverviewTile[]): (key: string) => string {
    const labelsById = new Map(tiles.map((tile) => [tile.id, tile.label]))
    return (key) => labelsById.get(key) ?? key
}

export function AccountsOverviewTiles(): JSX.Element {
    const { reconciledTiles, tileValues, tileQueryResponseLoading, editorVisible } =
        useValues(accountsOverviewTilesLogic)
    const { showEditor, hideEditor } = useActions(accountsOverviewTilesLogic)

    const overviewItems = reconciledTiles.map((tile) => tileToOverviewItem(tile, tileValues[tile.id] ?? null))

    return (
        <div className="flex flex-col gap-2" data-attr="accounts-overview-tiles">
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGear />}
                    onClick={showEditor}
                    data-attr="accounts-overview-tiles-edit"
                >
                    Edit overview tiles
                </LemonButton>
            </div>
            {reconciledTiles.length === 0 ? (
                <div className="border rounded p-6 flex flex-col items-center justify-center gap-2 text-secondary bg-surface-primary">
                    <span>No overview tiles configured.</span>
                    <LemonButton type="primary" size="small" onClick={showEditor}>
                        Add tile
                    </LemonButton>
                </div>
            ) : (
                <OverviewGrid
                    items={overviewItems}
                    loading={tileQueryResponseLoading}
                    numSkeletons={Math.max(reconciledTiles.length, 1)}
                    labelFromKey={tileLabelByKey(reconciledTiles)}
                />
            )}
            <AccountsOverviewTilesEditor isOpen={editorVisible} onClose={hideEditor} />
        </div>
    )
}
