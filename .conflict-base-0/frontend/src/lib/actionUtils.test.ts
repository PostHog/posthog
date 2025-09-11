import { elementToSelector } from 'lib/actionUtils'

import { ElementType } from '~/types'

describe('elementToSelector', () => {
    it('generates a data attr not an #ID', () => {
        const element = {
            attr_id: 'tomato',
        } as ElementType

        const actual = elementToSelector(element, [])
        expect(actual).toEqual('[id="tomato"]')
    })

    it('generates an incorrect class selector', () => {
        const element = {
            attr_class: ['potato', 'soup'],
        } as ElementType

        const actual = elementToSelector(element, [])
        expect(actual).toEqual('.potato.soup')
    })
})
