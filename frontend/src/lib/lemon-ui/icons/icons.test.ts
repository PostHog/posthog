import * as packageIcons from '@posthog/icons'

import { ELEMENTS, OBJECTS, TEAMS_AND_COMPANIES, TECHNOLOGY } from './categories'

describe('icons', () => {
    it('ensures all icons are categorised', async () => {
        const validPackageIcons = Object.keys(packageIcons).filter((i) => !['BaseIcon', 'default'].includes(i))
        const categories = { ...OBJECTS, ...TECHNOLOGY, ...ELEMENTS, ...TEAMS_AND_COMPANIES }
        const categorisedIcons = Object.values(categories)
            .map((category) => Object.values(category))
            .flat(2)

        expect(validPackageIcons.filter((i) => !categorisedIcons.includes(i))).toEqual([])
    })
})
