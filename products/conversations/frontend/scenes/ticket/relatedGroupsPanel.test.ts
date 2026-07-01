import { ActorType, GroupActorType } from '~/types'

import { orgBillingCustomerLink, shouldShowCreationFallback } from './RelatedGroupsPanel'

const group = (groupKey: string): ActorType => ({ type: 'group', group_key: groupKey }) as ActorType
const person = (): ActorType => ({ type: 'person' }) as ActorType
const orgGroup = (groupKey: string, groupTypeIndex: number): GroupActorType =>
    ({ type: 'group', group_key: groupKey, group_type_index: groupTypeIndex }) as GroupActorType

describe('RelatedGroupsPanel', () => {
    describe('shouldShowCreationFallback', () => {
        it.each<[string, string | null | undefined, ActorType[], boolean, number | null, boolean]>([
            ['no organization id', null, [], false, 0, false],
            ['related groups still loading', 'org-1', [], true, 0, false],
            ['organization group type not resolvable', 'org-1', [], false, null, false],
            ['snapshot group is already in the related list', 'org-1', [group('org-1')], false, 0, false],
            ['snapshot group is not in the related list', 'org-1', [group('other')], false, 0, true],
            ['no related groups at all', 'org-1', [], false, 0, true],
            ['matching group present alongside a person', 'org-1', [person(), group('org-1')], false, 0, false],
        ])('%s', (_label, organizationId, relatedActors, loading, orgGroupTypeIndex, expected) => {
            expect(shouldShowCreationFallback(organizationId, relatedActors, loading, orgGroupTypeIndex)).toBe(expected)
        })
    })

    describe('orgBillingCustomerLink', () => {
        // Guards the gating on an internal (billing.posthog.com) URL: it must render only for staff, only on
        // organization-type rows, and must be keyed by the org id via the `?q=` search.
        it('builds a billing-admin search link keyed by the org id for staff on an org row', () => {
            expect(orgBillingCustomerLink(orgGroup('org-uuid', 0), 0, true)).toEqual({
                to: 'https://billing.posthog.com/admin/billing/customer/?q=org-uuid',
                label: 'Billing →',
            })
        })

        it.each<[string, GroupActorType, number | null, boolean]>([
            ['non-staff user', orgGroup('org-uuid', 0), 0, false],
            ['org group type not resolvable', orgGroup('org-uuid', 0), null, true],
            ['row is a different group type', orgGroup('org-uuid', 1), 0, true],
        ])('returns null for %s', (_label, actor, orgGroupTypeIndex, isStaff) => {
            expect(orgBillingCustomerLink(actor, orgGroupTypeIndex, isStaff)).toBeNull()
        })
    })
})
