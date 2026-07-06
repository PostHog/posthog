import { ActorType } from '~/types'

import { shouldShowCreationFallback } from './RelatedGroupsPanel'

const group = (groupKey: string): ActorType => ({ type: 'group', group_key: groupKey }) as ActorType
const person = (): ActorType => ({ type: 'person' }) as ActorType

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
