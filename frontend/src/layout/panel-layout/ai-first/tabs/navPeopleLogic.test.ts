import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

import { Noun } from '~/models/groupsModel'
import { GroupType, GroupTypeIndex } from '~/types'

import { buildPeopleNavItems } from './navPeopleLogic'

const GROUP_TYPES = new Map<GroupTypeIndex, GroupType>([
    [0, { group_type: 'company', group_type_index: 0, name_plural: 'Companies' }],
    [1, { group_type: 'enemy', group_type_index: 1, name_plural: 'Enemies' }],
])

const aggregationLabel = (groupTypeIndex: number | null | undefined): Noun => ({
    singular: `group ${groupTypeIndex}`,
    plural: GROUP_TYPES.get(groupTypeIndex as GroupTypeIndex)?.name_plural ?? `groups ${groupTypeIndex}`,
})

describe('buildPeopleNavItems', () => {
    it('returns nothing when the flag is off', () => {
        expect(buildPeopleNavItems(false, GROUP_TYPES, GroupsAccessStatus.AlreadyUsing, aggregationLabel)).toEqual([])
    })

    it('adds one item per group type, labeled with its plural name', () => {
        const items = buildPeopleNavItems(true, GROUP_TYPES, GroupsAccessStatus.AlreadyUsing, aggregationLabel)

        expect(items.map((item) => [item.label, item.to])).toEqual([
            ['People', '/persons'],
            ['Companies', '/groups/0'],
            ['Enemies', '/groups/1'],
        ])
    })

    // Every status other than AlreadyUsing means the groups scenes render an upsell or an
    // introduction, so linking to them from the nav would dead-end the user.
    it.each([
        ['HasAccess', GroupsAccessStatus.HasAccess],
        ['HasGroupTypes', GroupsAccessStatus.HasGroupTypes],
        ['NoAccess', GroupsAccessStatus.NoAccess],
        ['Hidden', GroupsAccessStatus.Hidden],
    ] as const)('offers People alone when group access is %s', (_name, groupsAccessStatus) => {
        const items = buildPeopleNavItems(true, GROUP_TYPES, groupsAccessStatus, aggregationLabel)

        expect(items.map((item) => item.key)).toEqual(['people'])
    })
})
