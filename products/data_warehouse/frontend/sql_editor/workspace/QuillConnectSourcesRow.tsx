import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

/** The quiet prompt to connect a first source, in place of the Lemon sidebar's banner. */
export function QuillConnectSourcesRow(): JSX.Element | null {
    const { hasNonPosthogSources, syncMoreNoticeDismissed, databaseLoading } = useValues(queryDatabaseLogic)
    const { setSyncMoreNoticeDismissed } = useActions(queryDatabaseLogic)
    const { addProductIntent } = useActions(teamLogic)

    if (hasNonPosthogSources || syncMoreNoticeDismissed || databaseLoading) {
        return null
    }

    return (
        <div
            className="flex items-center gap-2 border-t p-2 ps-3"
            // pinned: data-attr read by autocapture dashboards for this prompt
            data-attr="sql-editor-source-empty-state"
        >
            <span className="flex shrink-0 -space-x-1">
                <SourceIcon type="Postgres" size="xsmall" disableTooltip />
                <SourceIcon type="Stripe" size="xsmall" disableTooltip />
                <SourceIcon type="GoogleAds" size="xsmall" disableTooltip />
            </span>
            <Button
                variant="link-foreground"
                size="sm"
                className="min-w-0 truncate"
                onClick={() => {
                    addProductIntent({
                        product_type: ProductKey.DATA_WAREHOUSE,
                        intent_context: ProductIntentContext.SQL_EDITOR_EMPTY_STATE,
                    })
                    router.actions.push(urls.dataWarehouseSourceNew())
                }}
                id="data-warehouse-sql-editor-add-data-source"
            >
                Connect Postgres, Stripe and more
            </Button>
            <Button
                size="icon-xs"
                className="ms-auto"
                aria-label="Dismiss"
                tooltip="Dismiss"
                onClick={() => setSyncMoreNoticeDismissed(true)}
            >
                <IconX />
            </Button>
        </div>
    )
}
