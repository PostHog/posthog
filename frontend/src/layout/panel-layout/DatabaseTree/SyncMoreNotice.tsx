import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconX } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { ProductIntentContext } from 'lib/utils/product-intents'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'

export const SyncMoreNotice = (): JSX.Element | null => {
    const { hasNonPosthogSources, syncMoreNoticeDismissed, databaseLoading } = useValues(queryDatabaseLogic)
    const { setSyncMoreNoticeDismissed } = useActions(queryDatabaseLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { showLayoutPanel, toggleLayoutPanelPinned, clearActivePanelIdentifier } = useActions(panelLayoutLogic)

    if (hasNonPosthogSources || syncMoreNoticeDismissed || databaseLoading) {
        return null
    }

    return (
        <LemonBanner type="info" className="m-2 h-[265px] min-h-[auto] z-10">
            <div
                data-attr="sql-editor-source-empty-state"
                className="p-4 text-center flex flex-col justify-center items-center relative"
            >
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => setSyncMoreNoticeDismissed(true)}
                    className="absolute top-0 right-0"
                    icon={<IconX />}
                />
                <div className="mb-4 flex justify-center gap-6">
                    <DataWarehouseSourceIcon type="Postgres" size="small" disableTooltip={true} />
                    <DataWarehouseSourceIcon type="Stripe" size="small" disableTooltip={true} />
                    <DataWarehouseSourceIcon type="GoogleAds" size="small" disableTooltip={true} />
                </div>
                <h4 className="mb-2">No data warehouse sources connected</h4>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <p className="text-muted mb-4 text-xs px-2 break-words w" style={{ whiteSpace: 'normal' }}>
                    Import data from external sources like Postgres, Stripe, or other databases to enrich your
                    analytics.
                </p>
                <LemonButton
                    type="primary"
                    onClick={() => {
                        addProductIntent({
                            product_type: ProductKey.DATA_WAREHOUSE,
                            intent_context: ProductIntentContext.SQL_EDITOR_EMPTY_STATE,
                        })
                        toggleLayoutPanelPinned(false)
                        showLayoutPanel(false)
                        clearActivePanelIdentifier()
                        router.actions.push(urls.dataWarehouseSourceNew())
                    }}
                    center
                    size="small"
                    id="data-warehouse-sql-editor-add-data-source"
                >
                    Add data source
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
