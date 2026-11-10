import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

export function NewDashboardMenu(): JSX.Element {
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { searchParams } = useValues(router)

    return (
        <>
            <LemonButton
                icon={<IconPlusSmall />}
                onClick={showNewDashboardModal}
                data-attr="new-dashboard-menu-item"
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>New dashboard</strong>
                    <span className="text-xs font-sans font-normal">Start blank or from a template</span>
                </div>
            </LemonButton>
            <LemonDivider className="my-1" />
            <LemonButton
                icon={<IconPencil />}
                to={combineUrl(urls.dashboardTemplates(), searchParams).url}
                // Pinned analytics value: insights built on clicks that open the templates list match on it.
                data-attr="view-dashboard-templates"
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>Manage templates</strong>
                    <span className="text-xs font-sans font-normal">Edit, share or delete your templates</span>
                </div>
            </LemonButton>
        </>
    )
}
