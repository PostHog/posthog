import { IntegrationType } from '~/types'

import { findIntegrationByFormValue, matchesIntegrationIdValue } from './integrationLookup'

const integration = (overrides: Partial<IntegrationType> = {}): IntegrationType => ({
    id: 7,
    kind: 'google-ads',
    icon_url: '',
    config: {},
    created_at: '2026-06-04T16:44:10Z',
    created_by: null,
    errors: '',
    display_name: 'test@posthog.com',
    ...overrides,
})

describe('matchesIntegrationIdValue', () => {
    it('matches when value is the same number', () => {
        expect(matchesIntegrationIdValue(7, 7)).toBe(true)
    })

    it('matches when value is a stringified number — regression', () => {
        // Reproduces the bug: integration IDs hydrated from a stored source's
        // JSONB job_inputs arrive as strings even though the API returns numbers.
        expect(matchesIntegrationIdValue(7, '7')).toBe(true)
    })

    it('does not match when ids differ', () => {
        expect(matchesIntegrationIdValue(7, 8)).toBe(false)
        expect(matchesIntegrationIdValue(7, '8')).toBe(false)
    })

    it.each([
        ['undefined', undefined],
        ['null', null],
        ['empty string', ''],
    ])('returns false for %s value (no selection)', (_label, value) => {
        expect(matchesIntegrationIdValue(7, value)).toBe(false)
    })

    it.each([
        ['non-numeric string', 'seven'],
        ['whitespace only', '   '],
        ['NaN-producing', 'not-a-number'],
    ])('returns false for non-numeric value (%s)', (_label, value) => {
        expect(matchesIntegrationIdValue(7, value)).toBe(false)
    })
})

describe('findIntegrationByFormValue', () => {
    const integrations = [integration({ id: 6 }), integration({ id: 7 })]

    it('finds the integration when value is a number', () => {
        expect(findIntegrationByFormValue(integrations, 7)?.id).toBe(7)
    })

    it('finds the integration when value is a stringified number — regression', () => {
        // The exact code path that was producing the "no longer available" banner
        // for every loaded source on the Configuration tab.
        expect(findIntegrationByFormValue(integrations, '7')?.id).toBe(7)
    })

    it('returns undefined when no integration matches', () => {
        expect(findIntegrationByFormValue(integrations, 99)).toBeUndefined()
        expect(findIntegrationByFormValue(integrations, '99')).toBeUndefined()
    })

    it.each([
        ['null integrations list (still loading)', null, 7],
        ['undefined integrations list', undefined, 7],
        ['undefined value', integrations, undefined],
        ['null value', integrations, null],
        ['empty-string value', integrations, ''],
    ])('returns undefined for %s', (_label, list, value) => {
        expect(findIntegrationByFormValue(list as IntegrationType[] | null | undefined, value as any)).toBeUndefined()
    })
})
