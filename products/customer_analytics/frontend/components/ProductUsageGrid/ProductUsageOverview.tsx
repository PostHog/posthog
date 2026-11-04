import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewGrid } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { NodeKind, type AccountsTableQueryResponse } from '~/queries/schema/schema-general'

import { parseTileValues, tileCaption } from '../Accounts/accountsOverviewTilesLogic'
import { PRODUCT_USAGE_OVERVIEW_KEY, productUsageOverviewLogic } from './productUsageOverviewLogic'

function ProductUsageOverviewValues(): JSX.Element {
    const { reconciledTiles } = useValues(productUsageOverviewLogic)
    const { response, responseLoading, responseError } = useValues(dataNodeLogic)
    const { loadData } = useActions(dataNodeLogic)
    // The query is fixed to AccountsTableQuery; reject unrelated data-node responses.
    const accountResponse =
        response?.kind === NodeKind.AccountsTableQuery ? (response as AccountsTableQueryResponse) : null
    const values = parseTileValues(accountResponse, reconciledTiles)
    return (
        <div data-attr="product-activity-overview">
            {responseError ? (
                <LemonBanner
                    type="warning"
                    action={
                        <LemonButton size="small" loading={responseLoading} onClick={() => loadData('force_async')}>
                            Retry
                        </LemonButton>
                    }
                >
                    Could not load account overview.
                </LemonBanner>
            ) : (
                <OverviewGrid
                    loading={responseLoading}
                    numSkeletons={reconciledTiles.length}
                    items={reconciledTiles.map((tile) => ({
                        key: tile.id,
                        value: values[tile.id] ?? undefined,
                        kind: tile.format ?? 'unit',
                        caption: tileCaption(tile),
                    }))}
                    labelFromKey={(key) => reconciledTiles.find((tile) => tile.id === key)?.label ?? key}
                />
            )}
        </div>
    )
}

export function ProductUsageOverview(): JSX.Element | null {
    const { query, tiles, tilesLoading, tilesError } = useValues(productUsageOverviewLogic)
    const { loadTiles } = useActions(productUsageOverviewLogic)
    if (tilesError) {
        return (
            <LemonBanner
                type="warning"
                action={
                    <LemonButton size="small" loading={tilesLoading} onClick={loadTiles}>
                        Retry
                    </LemonButton>
                }
            >
                Could not load configured account overview tiles.
            </LemonBanner>
        )
    }
    if (!query) {
        return tiles === null ? null : (
            <span className="text-secondary">
                No overview tiles configured.{' '}
                <Link to={urls.customerAnalyticsAccounts()}>Configure tiles in Accounts</Link>
            </span>
        )
    }
    return (
        <BindLogic logic={dataNodeLogic} props={{ key: PRODUCT_USAGE_OVERVIEW_KEY, query }}>
            <ProductUsageOverviewValues />
        </BindLogic>
    )
}
