import { ActorType } from '~/types'

import { relatedGroupsPersonUuid, shouldShowCreationFallback } from './RelatedGroupsPanel'

const group = (groupKey: string): ActorType => ({ type: 'group', group_key: groupKey }) as ActorType
const person = (): ActorType => ({ type: 'person' }) as ActorType

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

    describe('relatedGroupsPersonUuid', () => {
        const matchedPerson = { id: 'person-by-email', name: '', distinct_ids: ['user-42'], properties: {} }

        it.each<[string, Parameters<typeof relatedGroupsPersonUuid>[0], string | undefined, string | undefined]>([
            [
                'prefers the person loaded by distinct_id',
                { person: matchedPerson, anonymous_traits: {}, identity_verified: false },
                'person-by-distinct-id',
                'person-by-distinct-id',
            ],
            [
                'falls back to the email-matched person',
                { person: matchedPerson, anonymous_traits: {}, identity_verified: false },
                undefined,
                'person-by-email',
            ],
            [
                'ignores the email match on an unverified relayed email',
                { person: matchedPerson, anonymous_traits: { email_relayed: true }, identity_verified: false },
                undefined,
                undefined,
            ],
            [
                'keeps the email match on a verified relayed email',
                { person: matchedPerson, anonymous_traits: { email_relayed: true }, identity_verified: true },
                undefined,
                'person-by-email',
            ],
            [
                'has no person without a match',
                { person: null, anonymous_traits: {}, identity_verified: false },
                undefined,
                undefined,
            ],
        ])('%s', (_label, ticket, loadedPersonUuid, expected) => {
            expect(relatedGroupsPersonUuid(ticket, loadedPersonUuid)).toBe(expected)
        })
    })
})
