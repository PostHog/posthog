import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'
import { urls } from 'scenes/urls'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree(): JSX.Element {
    const isOnSqlEditor = router.values.location.pathname.endsWith(urls.sqlEditor())

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
            <QueryDatabase />
            <SyncMoreNotice />
            <ViewLinkModal />
        </PanelLayoutPanel>
    )
}
