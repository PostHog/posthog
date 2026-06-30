import { useValues } from 'kea'

import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { ActorType } from '~/types'

const HIGHLIGHT_LABEL = 'Active at creation'

interface RelatedGroupsPanelProps {
    personUuid: string
    // The group the ticket was created with (organization group key), snapshotted at creation.
    organizationId?: string | null
}

// Show the standalone "active at creation" line only when the snapshot group exists but isn't already
// in the person's live related groups (e.g. it aged out of the related-groups window) — so we never
// duplicate a row that the table already highlights, and never hide the snapshot when it's missing.
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

    const showFallback = shouldShowCreationFallback(
        organizationId,
        relatedActors,
        relatedActorsLoading,
        orgGroupTypeIndex
    )

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="related-groups"
            panels={[
                {
                    key: 'related-groups',
                    header: 'Related groups',
                    content: (
                        <div className="space-y-2">
                            <RelatedGroups
                                id={personUuid}
                                groupTypeIndex={null}
                                embedded
                                highlightGroupKey={organizationId}
                                highlightLabel={HIGHLIGHT_LABEL}
                            />
                            {showFallback && organizationId && orgGroupTypeIndex !== null && (
                                <div className="flex items-center gap-2 px-2 text-sm">
                                    <LemonTag type="highlight" size="small">
                                        {HIGHLIGHT_LABEL}
                                    </LemonTag>
                                    <Link to={urls.group(orgGroupTypeIndex.toString(), organizationId)}>
                                        <span className="ph-no-capture">{groupDisplayId(organizationId, {})}</span>
                                    </Link>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
