import * as packageIcons from '@posthog/icons'

import { CATEGORIES, UNUSED_ICONS } from './icons3000.stories'

describe('icons', () => {
    it('ensures all icons are categorised', async () => {
        const validPackageIcons = Object.keys(packageIcons).filter((i) => !['BaseIcon', 'default'].includes(i))
        const categorisedIcons = Object.values(CATEGORIES)
            .map((category) => Object.values(category))
            .flat(2)

        const allIcons = [...categorisedIcons, ...UNUSED_ICONS]

        expect(validPackageIcons.filter((i) => !allIcons.includes(i))).toEqual([])
    })
})
