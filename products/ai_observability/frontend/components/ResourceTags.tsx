import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { TaggedResource } from './resourceTagFilters'
import { resourceTagsLogic } from './resourceTagsLogic'
import { ResourceTagsModal } from './ResourceTagsModal'

export function ResourceTags({
    entity,
    resourceId,
    tags,
    onSaved,
    onTagClick,
    userAccessLevel,
    disabledReason,
}: {
    entity: TaggedResource
    resourceId: string
    tags: readonly string[]
    onSaved: () => void
    onTagClick: (tag: string) => void
    userAccessLevel?: AccessControlLevel
    disabledReason?: string
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = resourceTagsLogic({ entity, resourceId, tags, onSaved, teamId: currentTeamId ?? 0 })
    const { isOpen } = useValues(logic)
    const { open } = useActions(logic)
    return (
        <div className="flex items-start gap-1 min-w-0 max-w-64">
            <ObjectTags
                tags={[...tags]}
                staticOnly
                maxVisibleTags={2}
                wrap
                onTagClick={onTagClick}
                data-attr="aio-resource-tags"
            />
            <AccessControlAction
                resourceType={
                    entity === 'experiments'
                        ? AccessControlResourceType.Evaluation
                        : AccessControlResourceType.LlmAnalytics
                }
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={userAccessLevel}
            >
                <LemonButton
                    icon={<IconPencil />}
                    size="xsmall"
                    disabledReason={disabledReason}
                    tooltip="Edit tags"
                    aria-label="Edit tags"
                    onClick={open}
                    data-attr="aio-resource-tags-edit"
                />
            </AccessControlAction>
            {isOpen && <ResourceTagsModal logic={logic} />}
        </div>
    )
}
