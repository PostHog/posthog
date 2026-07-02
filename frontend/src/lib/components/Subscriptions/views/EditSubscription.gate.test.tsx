import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'

import { integrationHasFilesWrite } from '../utils'
import { isFreeTierCreateAtLimit } from './EditSubscription'

const LIMIT = SubscriptionFreeTierLimit.COUNT

describe('EditSubscription free-tier gate', () => {
    it.each([
        ['empty (first use)', 0, false],
        ['one below the limit boundary', LIMIT - 1, false],
        ['at the limit', LIMIT, true],
        ['over the limit', LIMIT + 1, true],
    ])('blocks the next create when %s (count=%i) -> %s', (_desc, count, expected) => {
        expect(isFreeTierCreateAtLimit(count)).toBe(expected)
    })

    it('fails open while the count is unknown (null) so the form shows; backend enforces the hard limit', () => {
        expect(isFreeTierCreateAtLimit(null)).toBe(false)
    })
})

describe('EditSubscription slack gallery gate', () => {
    it.each<[string, string | null | undefined, boolean]>([
        ['files:write is granted', 'chat:write,files:write,channels:read', true],
        ['files:write is absent', 'chat:write,channels:read', false],
        ['the scope string is empty', '', false],
        ['the scope is null', null, false],
        ['the scope is undefined', undefined, false],
        // files:write:advanced (substring) must not match the exact files:write scope
        ['files:write only appears as a substring', 'files:write:advanced', false],
    ])('integrationHasFilesWrite is %s -> %s', (_desc, scope, expected) => {
        expect(integrationHasFilesWrite(scope)).toBe(expected)
    })
})
