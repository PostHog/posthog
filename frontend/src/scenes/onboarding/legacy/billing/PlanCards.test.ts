import { BillingFeatureType } from '~/types'

import { formatDataRetentionFeature } from './PlanCards'

describe('formatDataRetentionFeature', () => {
    const makeFeature = (limit?: number | null, unit?: string | null): BillingFeatureType =>
        ({ key: 'session_replay_data_retention', name: 'Data retention', limit, unit }) as BillingFeatureType

    // pluralize() joins the count and unit with a non-breaking space (U+00A0); normalize it for readable assertions.
    const normalize = (value: string | null): string | null =>
        value ? value.split(String.fromCharCode(160)).join(' ') : null

    it.each([
        // Analytics retention is supplied in years; session replay in months. Both must read naturally.
        [7, 'years', '7 years data retention'],
        [1, 'year', '1 year data retention'],
        [3, 'months', '3 months data retention'],
        [1, 'month', '1 month data retention'],
        [90, 'days', '90 days data retention'],
    ])('formats limit %s with unit "%s" as "%s"', (limit, unit, expected) => {
        expect(normalize(formatDataRetentionFeature(makeFeature(limit, unit)))).toBe(expected)
    })

    it.each([
        ['feature is undefined', undefined],
        ['limit is missing', makeFeature(undefined, 'years')],
        ['unit is missing', makeFeature(7, undefined)],
    ])('returns null when %s', (_, feature) => {
        expect(formatDataRetentionFeature(feature as BillingFeatureType | undefined)).toBe(null)
    })
})
