import { IconPlus, IconX } from '@posthog/icons'
import { router } from 'kea-router'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabaseTreeView } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'
import { urls } from 'scenes/urls'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PipelineStage, ProductKey } from '~/types'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { panelLayoutLogic } from '../panelLayoutLogic'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'

export function DatabaseTree(): JSX.Element {
    const isOnSqlEditor = router.values.location.pathname.endsWith(urls.sqlEditor())
    const { addProductIntent } = useActions(teamLogic)
    const { showLayoutPanel, toggleLayoutPanelPinned, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { setSyncMoreNoticeDismissed } = useActions(queryDatabaseLogic)
    const { hasNonPosthogSources, syncMoreNoticeDismissed } = useValues(queryDatabaseLogic)

    return (
        <PanelLayoutPanel
            searchField={<DatabaseSearchField placeholder="Search database" />}
            panelActions={
                !isOnSqlEditor ? (
                    <ButtonPrimitive
                        onClick={() => {
                            router.actions.push(urls.sqlEditor())
                        }}
                        tooltip="New query"
                        iconOnly
                        data-attr="tree-panel-new-query-button"
                    >
                        <IconPlus className="text-tertiary" />
                    </ButtonPrimitive>
                ) : undefined
            }
        >
            <QueryDatabaseTreeView />
            {!hasNonPosthogSources && !syncMoreNoticeDismissed && (
                <LemonBanner type="info" className="m-2 absolute bottom-0 left-0 right-0 z-10">
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
                            <DataWarehouseSourceIcon type="Postgres" size="small" />
                            <DataWarehouseSourceIcon type="Stripe" size="small" />
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
                                setActivePanelIdentifier('')
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
            )}
            <ViewLinkModal />
        </PanelLayoutPanel>
    )
}
