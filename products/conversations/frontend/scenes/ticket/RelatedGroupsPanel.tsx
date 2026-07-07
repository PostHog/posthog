import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'

import { groupsModel } from '~/models/groupsModel'
import { ActorType, GroupActorType } from '~/types'

import { creationGroupLogic } from './creationGroupLogic'

const HIGHLIGHT_LABEL = 'Ticket origin'
const STALE_TOOLTIP =
    "This group was active when the ticket was created, but it's no longer in the person's recent related groups."

interface RelatedGroupsPanelProps {
    personUuid: string
    // The group the ticket was created with (organization group key), snapshotted at creation.
    organizationId?: string | null
}

// Append the creation group as its own row only when it exists but isn't already in the person's live
// related groups (e.g. it aged out of the related-groups window) — so we never duplicate a highlighted
// row and never hide the snapshot when it's missing from the live list.
export function shouldShowCreationFallback(
    organizationId: string | null | undefined,
    relatedActors: ActorType[],
    relatedActorsLoading: boolean,
    orgGroupTypeIndex: number | null
): boolean {
    if (!organizationId || relatedActorsLoading || orgGroupTypeIndex === null) {
        return false
    }
    return !relatedActors.some((actor) => actor.type === 'group' && actor.group_key === organizationId)
}

export function RelatedGroupsPanel({ personUuid, organizationId }: RelatedGroupsPanelProps): JSX.Element {
    const { relatedActors, relatedActorsLoading } = useValues(
        relatedGroupsLogic({ groupTypeIndex: null, id: personUuid })
    )
    const { groupTypes } = useValues(groupsModel)

    // `organization_id` is always a key of the "organization" group type (set that way at creation),
    // so we can resolve its index by name when the group has dropped out of the live related list.
    const orgGroupTypeIndex =
        Array.from(groupTypes.values()).find((gt) => gt.group_type === 'organization')?.group_type_index ?? null

    const { group: creationGroup } = useValues(
        creationGroupLogic({ groupTypeIndex: orgGroupTypeIndex, groupKey: organizationId ?? null })
    )

    const showFallback = shouldShowCreationFallback(
        organizationId,
        relatedActors,
        relatedActorsLoading,
        orgGroupTypeIndex
    )

    // When the snapshot group isn't in the live related list, fetch it and append it as a real row
    // (type + name + link) rather than a bare key, tagged via highlightGroupKey below.
    const extraActors: ActorType[] =
        showFallback && creationGroup
            ? [
                  {
                      type: 'group',
                      id: creationGroup.group_key,
                      group_key: creationGroup.group_key,
                      group_type_index: creationGroup.group_type_index,
                      properties: creationGroup.group_properties,
                      created_at: creationGroup.created_at,
                  } as GroupActorType,
              ]
            : []

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="related-groups"
            panels={[
                {
                    key: 'related-groups',
                    header: 'Related groups',
                    content: (
                        <RelatedGroups
                            id={personUuid}
                            groupTypeIndex={null}
                            embedded
                            highlightGroupKey={organizationId}
                            highlightLabel={HIGHLIGHT_LABEL}
                            highlightStale={showFallback}
                            highlightStaleTooltip={STALE_TOOLTIP}
                            extraActors={extraActors}
                        />
                    ),
                },
            ]}
        />
    )
}
