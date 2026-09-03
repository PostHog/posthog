import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import * as packageIcons from '@posthog/icons'

import { ELEMENTS, OBJECTS, TEAMS_AND_COMPANIES, TECHNOLOGY } from './categories'
import { IconCollection } from './icons3000.stories'

describe('icons', () => {
    it('ensures all icons are categorised', async () => {
        const validPackageIcons = (Object.keys(packageIcons) as IconCollection).filter(
            (i) => !['BaseIcon', 'default'].includes(i)
        )
        const categories = { ...OBJECTS, ...TECHNOLOGY, ...ELEMENTS, ...TEAMS_AND_COMPANIES }
        const categorisedIcons = Object.values(categories)
            .map((category) => Object.values(category))
            .flat(2)

        expect(validPackageIcons.filter((i) => !categorisedIcons.includes(i))).toEqual([])
    })

    // A container-relative width makes an icon fill its parent until .LemonIcon applies.
    // patches/@posthog__icons@0.38.0.patch keeps the units em-based; re-create it on a bump.
    it('ensures package icons carry em-based intrinsic dimensions', () => {
        const markup = renderToStaticMarkup(createElement(packageIcons.IconX))

        expect(markup).toContain('width="1em"')
        expect(markup).toContain('height="1em"')
    })
})
