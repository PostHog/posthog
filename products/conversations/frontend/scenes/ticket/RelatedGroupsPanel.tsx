import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonCollapse, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { groupsModel } from '~/models/groupsModel'
import { ActorType, Group, GroupActorType } from '~/types'

import { RelatedGroups } from 'products/groups/frontend/components/RelatedGroups'
import { relatedGroupsLogic } from 'products/groups/frontend/logics/relatedGroupsLogic'
import { GroupActorDisplay } from 'products/persons/frontend/components/GroupActorDisplay'

import { GroupRevenue } from '../../components/GroupRevenue/GroupRevenue'
import { creationGroupLogic } from './creationGroupLogic'
import { resolveGroupRevenue } from './groupRevenue'
import { groupRevenueLogic } from './groupRevenueLogic'

const ORIGIN_LABEL = 'Ticket origin'
const STALE_TOOLTIP =
    "This group was active when the ticket was created, but it's no longer in the person's recent related groups."
const CHANNEL_ACCOUNT_LABEL = 'Customer analytics'
const CHANNEL_ACCOUNT_TOOLTIP =
    "This group was inferred from the customer analytics account associated with the ticket's Slack channel, not from the requester's identity."

export const SLACK_CHANNEL_ACCOUNT_SOURCE = 'slack_channel_account'

interface RelatedGroupsPanelProps {
    personUuid?: string | null
    // The group the ticket was created with (organization group key), snapshotted at creation.
    organizationId?: string | null
    // How organization_id was resolved ("person" or "slack_channel_account").
    organizationIdSource?: string | null
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

// `organization_id` is always a key of the "organization" group type (set that way at creation),
// so we can resolve its index by name when the group isn't in a live related list.
function useOrgGroupTypeIndex(): { orgGroupTypeIndex: number | null; groupTypesLoading: boolean } {
    const { groupTypes, groupTypesLoading } = useValues(groupsModel)
    return {
        orgGroupTypeIndex:
            Array.from(groupTypes.values()).find((gt) => gt.group_type === 'organization')?.group_type_index ?? null,
        groupTypesLoading,
    }
}

function toGroupActor(group: Group): GroupActorType {
    return {
        type: 'group',
        id: group.group_key,
        group_key: group.group_key,
        group_type_index: group.group_type_index,
        properties: group.group_properties,
        created_at: group.created_at,
    } as GroupActorType
}

function GroupRevenueDetail({ actor, groupKeys }: { actor: GroupActorType; groupKeys: string[] }): JSX.Element {
    const { revenueByGroupKey, revenueByGroupKeyLoading } = useValues(groupRevenueLogic({ groupKeys }))
    return (
        <GroupRevenue
            revenue={resolveGroupRevenue(revenueByGroupKey[actor.group_key], actor.properties)}
            loading={revenueByGroupKeyLoading}
        />
    )
}

function PersonRelatedGroups({
    personUuid,
    organizationId,
    fromChannelAccount,
}: {
    personUuid: string
    organizationId?: string | null
    fromChannelAccount: boolean
}): JSX.Element {
    const { relatedActors, relatedActorsLoading } = useValues(
        relatedGroupsLogic({ groupTypeIndex: null, id: personUuid })
    )
    const { orgGroupTypeIndex } = useOrgGroupTypeIndex()

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
    const extraActors = useMemo<ActorType[]>(
        () => (showFallback && creationGroup ? [toGroupActor(creationGroup)] : []),
        [showFallback, creationGroup]
    )

    // Every row reads from one logic keyed by the full list, so the panel issues a single revenue query.
    const groupKeys = useMemo(
        () =>
            Array.from(
                new Set(
                    [...relatedActors, ...extraActors].flatMap((actor) =>
                        actor.type === 'group' ? [actor.group_key] : []
                    )
                )
            ),
        [relatedActors, extraActors]
    )
    const renderGroupDetail = useCallback(
        (actor: GroupActorType) => <GroupRevenueDetail actor={actor} groupKeys={groupKeys} />,
        [groupKeys]
    )

    return (
        <RelatedGroups
            id={personUuid}
            groupTypeIndex={null}
            embedded
            highlightGroupKey={organizationId}
            highlightLabel={fromChannelAccount ? CHANNEL_ACCOUNT_LABEL : ORIGIN_LABEL}
            highlightLabelTooltip={fromChannelAccount ? CHANNEL_ACCOUNT_TOOLTIP : undefined}
            // A channel-inferred group was never tied to the person, so "stale" (dropped out of the
            // person's recent groups) doesn't apply to it.
            highlightStale={!fromChannelAccount && showFallback}
            highlightStaleTooltip={STALE_TOOLTIP}
            extraActors={extraActors}
            renderGroupDetail={renderGroupDetail}
        />
    )
}

// No person to query related groups for — show just the creation-snapshot group.
function CreationGroupOnly({
    organizationId,
    fromChannelAccount,
}: {
    organizationId: string
    fromChannelAccount: boolean
}): JSX.Element {
    const { orgGroupTypeIndex, groupTypesLoading } = useOrgGroupTypeIndex()
    const { group: creationGroup, groupLoading } = useValues(
        creationGroupLogic({ groupTypeIndex: orgGroupTypeIndex, groupKey: organizationId })
    )

    // While group types are loading, the index is transiently null and the group lookup
    // no-ops — hold the loading state rather than flashing the empty state.
    if (groupTypesLoading || groupLoading) {
        return <Spinner />
    }
    if (!creationGroup) {
        return <div className="text-secondary">No related groups found</div>
    }

    const creationActor = toGroupActor(creationGroup)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <GroupActorDisplay actor={creationActor} />
                <Tooltip title={fromChannelAccount ? CHANNEL_ACCOUNT_TOOLTIP : undefined}>
                    <LemonTag type="muted" size="small">
                        {fromChannelAccount ? CHANNEL_ACCOUNT_LABEL : ORIGIN_LABEL}
                    </LemonTag>
                </Tooltip>
            </div>
            <GroupRevenueDetail actor={creationActor} groupKeys={[creationActor.group_key]} />
        </div>
    )
}

export function RelatedGroupsPanel({
    personUuid,
    organizationId,
    organizationIdSource,
}: RelatedGroupsPanelProps): JSX.Element | null {
    const fromChannelAccount = organizationIdSource === SLACK_CHANNEL_ACCOUNT_SOURCE

    let content: JSX.Element | null = null
    if (personUuid) {
        content = (
            <PersonRelatedGroups
                personUuid={personUuid}
                organizationId={organizationId}
                fromChannelAccount={fromChannelAccount}
            />
        )
    } else if (organizationId) {
        content = <CreationGroupOnly organizationId={organizationId} fromChannelAccount={fromChannelAccount} />
    }
    if (!content) {
        return null
    }

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="related-groups"
            panels={[
                {
                    key: 'related-groups',
                    header: 'Related groups',
                    content,
                },
            ]}
        />
    )
}
