import { PropertyDefinitionType } from '~/types'

import { isCoreFilter } from './helpers'

describe('isCoreFilter', () => {
    it.each<[string, PropertyDefinitionType | undefined, boolean]>([
        ['title', undefined, true],
        ['title', PropertyDefinitionType.Person, false],
        ['utm_source', PropertyDefinitionType.Person, true],
    ])('%s with type %s is core: %s', (key, type, expected) => {
        expect(isCoreFilter(key, type)).toBe(expected)
    })
})
