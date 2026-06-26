import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'

import { integrationHasFilesWrite, isFreeTierCreateAtLimit } from './EditSubscription'

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
    describe('integrationHasFilesWrite', () => {
        it('returns true when files:write is in the scope string', () => {
            expect(integrationHasFilesWrite('chat:write,files:write,channels:read')).toBe(true)
        })

        it('returns false when files:write is absent from the scope string', () => {
            expect(integrationHasFilesWrite('chat:write,channels:read')).toBe(false)
        })

        it('returns false for an empty scope string', () => {
            expect(integrationHasFilesWrite('')).toBe(false)
        })

        it('returns false for null scope', () => {
            expect(integrationHasFilesWrite(null)).toBe(false)
        })

        it('returns false for undefined scope', () => {
            expect(integrationHasFilesWrite(undefined)).toBe(false)
        })

        it('does not false-positive on a scope that contains files:write as a substring', () => {
            // e.g. a hypothetical "files:write:advanced" must not match
            expect(integrationHasFilesWrite('files:write:advanced')).toBe(false)
        })
    })
})
