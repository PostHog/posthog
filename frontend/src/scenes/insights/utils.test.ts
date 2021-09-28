import { Entity, EntityFilter } from '~/types'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

const createFilter = (id?: Entity['id'], name?: string, custom_name?: string): EntityFilter => {
    return {
        custom_name,
        name: name ?? null,
        id: id ?? null,
    }
}

describe('getDisplayNameFromEntityFilter()', () => {
    it('returns values correctly', () => {
        const paramsToExpected: [EntityFilter, boolean, string | null][] = [
            [createFilter(3, 'name', 'custom_name'), true, 'custom_name'],
            [createFilter(3, 'name', ''), true, 'name'],
            [createFilter(3, 'name', '    '), true, 'name'],
            [createFilter(3, 'name'), true, 'name'],
            [createFilter(3, '', ''), true, '3'],
            [createFilter(3, '  ', '    '), true, '3'],
            [createFilter(3), true, '3'],
            [createFilter('hi'), true, 'hi'],
            [createFilter(), true, null],
            [createFilter(3, 'name', 'custom_name'), false, 'name'],
            [createFilter(3, '  ', 'custom_name'), false, '3'],
        ]

        paramsToExpected.forEach(([filter, isCustom, expected]) => {
            expect(getDisplayNameFromEntityFilter(filter, isCustom)).toEqual(expected)
        })
    })
})
