import { GroupType } from '~/types'

import { buildGroupAnalyticsTaxonomicGroups } from './buildGroupAnalyticsGroups'

describe('buildGroupAnalyticsTaxonomicGroups', () => {
    it('lists group properties without hidden or restricted ones, like the legacy picker', () => {
        const groupTypes = new Map([[0, { group_type: 'organization', group_type_index: 0 } as unknown as GroupType]])
        const [group] = buildGroupAnalyticsTaxonomicGroups(groupTypes, 1, () => ({
            singular: 'organization',
            plural: 'organizations',
        }))

        const params = new URLSearchParams(group.endpoint!.split('?')[1])
        expect(params.get('type')).toBe('group')
        expect(params.get('group_type_index')).toBe('0')
        expect(params.get('exclude_hidden')).toBe('true')
        expect(params.get('exclude_restricted')).toBe('true')
    })
})
