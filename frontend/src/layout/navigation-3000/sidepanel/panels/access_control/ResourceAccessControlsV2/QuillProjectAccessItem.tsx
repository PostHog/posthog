import { useActions, useValues } from 'kea'

import { IconHome, IconInfo } from '@posthog/icons'
import {
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { accessControlsLogic } from './accessControlsLogic'
import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { getEntryId, getLevelOptionsForResource, inheritedFor } from './helpers'
import { QuillLevelSelect } from './QuillLevelSelect'
import type { AccessControlSettingsEntry } from './types'

export function QuillProjectAccessItem({
    projectId,
    scopeType,
    entry,
    cannotEditReason,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
    cannotEditReason: string | undefined
}): JSX.Element {
    const { availableProjectLevels } = useValues(accessControlsLogic({ projectId }))
    const { setSubjectProjectAccess } = useActions(accessControlsLogic({ projectId }))
    const { currentTeam } = useValues(teamLogic)

    const subjectId = getEntryId(entry)

    return (
        <Item variant="outline" size="sm">
            <ItemMedia>
                <IconHome />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>
                    Project access
                    <Tooltip>
                        <TooltipTrigger
                            aria-label="About project access levels"
                            render={<span className="flex items-center text-muted-foreground" />}
                        >
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent>
                            <div className="flex flex-col gap-1">
                                <span>
                                    <b>Admin</b>: change project settings, rename or delete the project, and manage
                                    access.
                                </span>
                                <span>
                                    <b>Member</b>: open and use the project, with access to each product set below.
                                </span>
                                <span>
                                    <b>No access</b>: the project is hidden entirely.
                                </span>
                            </div>
                        </TooltipContent>
                    </Tooltip>
                </ItemTitle>
                {currentTeam?.name && <ItemDescription>{currentTeam.name}</ItemDescription>}
            </ItemContent>
            <ItemActions>
                <QuillLevelSelect
                    aria-label="Project access"
                    value={entry.project.access_level}
                    options={getLevelOptionsForResource(availableProjectLevels)}
                    onChange={(level) => setSubjectProjectAccess(scopeType, subjectId, level)}
                    disabledReason={cannotEditReason}
                    inherited={inheritedFor(entry.project, 'this project')}
                    // A subject with nothing above them falls back to the project's own default, which the
                    // entry doesn't resolve, so "No override" is offered without naming a level
                    allowNoOverride
                    data-attr="access-detail-project-access"
                    className="w-56"
                />
            </ItemActions>
        </Item>
    )
}
