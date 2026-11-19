import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconChevronDown, IconPencil, IconPlus } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function QuillDashboardsActions(): JSX.Element {
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { searchParams } = useValues(router)
    const { push } = useActions(router)
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor
    )

    return (
        <ButtonGroup>
            <AccessControlAction
                resourceType={AccessControlResourceType.Dashboard}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Shortcut
                    name="NewDashboard"
                    keybind={[keyBinds.new]}
                    intent="New dashboard"
                    interaction="click"
                    scope={Scene.Dashboards}
                >
                    <Button variant="primary" data-attr="new-dashboard" onClick={showNewDashboardModal}>
                        New dashboard
                    </Button>
                </Shortcut>
            </AccessControlAction>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="More dashboard options"
                            data-attr="new-dashboard-dropdown"
                            disabledReason={accessDisabledReason}
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-64">
                    <DropdownMenuItem
                        onClick={showNewDashboardModal}
                        data-attr="new-dashboard-menu-item"
                        description="Start blank or from a template"
                    >
                        <IconPlus />
                        New dashboard
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        onClick={() => push(combineUrl(urls.dashboardTemplates(), searchParams).url)}
                        // Pinned analytics value: insights built on clicks that open the templates list match on it.
                        data-attr="view-dashboard-templates"
                        description="Edit, share or delete your templates"
                    >
                        <IconPencil />
                        Manage templates
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
