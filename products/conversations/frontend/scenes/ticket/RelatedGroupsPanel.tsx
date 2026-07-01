import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { ActorType, GroupActorType } from '~/types'

import { creationGroupLogic } from './creationGroupLogic'

const HIGHLIGHT_LABEL = 'Ticket origin'
const STALE_TOOLTIP =
    "This group was active when the ticket was created, but it's no longer in the person's recent related groups."
const BILLING_ADMIN_ORIGIN = 'https://billing.posthog.com'

// Staff-only: link an organization group row to its billing customer in billing admin. The org group's key is the
// organization UUID, so we search billing admin by org id (the same `?q=` lookup PostHog's org admin uses) — this
// resolves the customer even when no Stripe/billing id is recorded on the account. Returns null for non-org rows
// or non-staff users so the internal URL never renders for customers.
export function orgBillingCustomerLink(
    actor: GroupActorType,
    orgGroupTypeIndex: number | null,
    isStaff: boolean
): { to: string; label: string } | null {
    if (!isStaff || orgGroupTypeIndex === null || actor.group_type_index !== orgGroupTypeIndex) {
        return null
    }
    return { to: `${BILLING_ADMIN_ORIGIN}/admin/billing/customer/?q=${actor.group_key}`, label: 'Billing →' }
}

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
    const { user } = useValues(userLogic)

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
                            groupRowLink={(actor) => orgBillingCustomerLink(actor, orgGroupTypeIndex, !!user?.is_staff)}
                        />
                    ),
                },
            ]}
        />
    )
}
