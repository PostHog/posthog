import { ProductKey } from '~/queries/schema/schema-general'

import { PRODUCT_PUSH_DISPLAY } from './navPanelProductPushDisplay'
import { PRODUCT_PUSH_PROMPTS } from './productPushPrompts'

describe('PRODUCT_PUSH_PROMPTS', () => {
    it('has a Today prompt for every product the sidebar card can push', () => {
        // Self-driving is out of the push rotation. Its display stays for campaigns that started before.
        const pushable = Object.keys(PRODUCT_PUSH_DISPLAY).filter((key) => key !== ProductKey.SELF_DRIVING)

        expect(pushable.filter((key) => !PRODUCT_PUSH_PROMPTS[key])).toEqual([])
    })
})
