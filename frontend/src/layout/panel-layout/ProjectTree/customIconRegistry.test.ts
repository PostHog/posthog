import { SupportNavBadge } from 'products/conversations/frontend/components/SupportNavBadge'

import { getCustomIcon } from './customIconRegistry'

describe('customIconRegistry', () => {
    it.each<[string | undefined, boolean]>([
        ['/support', true],
        ['/support/tickets', true],
        ['/project/1/support/tickets?status=open', true],
        ['/support?status=open', true],
        ['/business-knowledge', false],
        ['/project/1/business-knowledge', false],
        ['/my-tickets', false],
        ['/support-other', false],
        [undefined, false],
    ])('only shows the Support unread count for Support links (%s)', (href, hasBadge) => {
        expect(getCustomIcon('conversations', href)).toBe(hasBadge ? SupportNavBadge : undefined)
    })
})
