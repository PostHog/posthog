import * as packageIcons from '@posthog/icons'

import { ELEMENTS, OBJECTS, TEAMS_AND_COMPANIES, TECHNOLOGY, UNUSED_ICONS } from './categories'

describe('icons', () => {
    it('ensures all icons are categorised', async () => {
        const validPackageIcons = Object.keys(packageIcons).filter((i) => !['BaseIcon', 'default'].includes(i))
        const categories = { ...OBJECTS, ...TECHNOLOGY, ...ELEMENTS, ...TEAMS_AND_COMPANIES }
        const categorisedIcons = Object.values(categories)
            .map((category) => Object.values(category))
            .flat(2)

        const allIcons = [...categorisedIcons, ...UNUSED_ICONS]

        expect(validPackageIcons.filter((i) => !allIcons.includes(i))).toEqual([])
    })
})
