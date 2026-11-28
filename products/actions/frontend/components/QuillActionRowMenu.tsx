import { useActions } from 'kea'

import { IconCopy, IconEllipsis, IconGraph, IconPencil, IconRewindPlay, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ActionType, ReplayTabs } from '~/types'

import { actionRecordingsFilters } from '../utils/actionRecordingsFilters'
import { actionTrendsInsightUrl } from '../utils/actionTrendsInsightUrl'

export function QuillActionRowMenu({ action, onDelete }: { action: ActionType; onDelete: () => void }): JSX.Element {
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const viewRecordings = (): void => {
        addProductIntentForCrossSell({
            from: ProductKey.ACTIONS,
            to: ProductKey.SESSION_REPLAY,
            intent_context: ProductIntentContext.ACTION_VIEW_RECORDINGS,
        })
        newInternalTab(urls.replay(ReplayTabs.Home, actionRecordingsFilters(action)))
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${action.name || 'unnamed action'}`}
                        data-attr="action-table-row-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuGroup>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Action}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={action.user_access_level}
                    >
                        <DropdownMenuItem render={<LinkPrimitive to={urls.action(action.id)} />}>
                            <IconPencil />
                            Edit
                        </DropdownMenuItem>
                    </AccessControlAction>
                    <DropdownMenuItem render={<LinkPrimitive to={urls.duplicateAction(action)} />}>
                        <IconCopy />
                        Duplicate
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={viewRecordings} data-attr="action-table-view-recordings">
                        <IconRewindPlay />
                        View recordings
                    </DropdownMenuItem>
                    <DropdownMenuItem render={<LinkPrimitive to={actionTrendsInsightUrl(action)} target="_blank" />}>
                        <IconGraph />
                        Try out in Insights
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <AccessControlAction
                    resourceType={AccessControlResourceType.Action}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={action.user_access_level}
                >
                    <DropdownMenuItem variant="destructive" onClick={onDelete}>
                        <IconTrash />
                        Delete action
                    </DropdownMenuItem>
                </AccessControlAction>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
