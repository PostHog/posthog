import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconX } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { ProductIntentContext } from 'lib/utils/product-intents'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { PipelineStage, ProductKey } from '~/types'

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
        <LemonBanner type="info" className="absolute bottom-0 left-0 right-0 z-10 m-2">
            <div
                data-attr="sql-editor-source-empty-state"
                className="relative flex flex-col items-center justify-center p-4 text-center"
            >
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => setSyncMoreNoticeDismissed(true)}
                    className="absolute right-0 top-0"
                    icon={<IconX />}
                />
                <div className="mb-4 flex justify-center gap-6">
                    <DataWarehouseSourceIcon type="Postgres" size="small" />
                    <DataWarehouseSourceIcon type="Stripe" size="small" />
                </div>
                <h4 className="mb-2">No data warehouse sources connected</h4>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <p className="text-muted w mb-4 break-words px-2 text-xs" style={{ whiteSpace: 'normal' }}>
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
                        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
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
