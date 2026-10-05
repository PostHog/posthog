import { PropertyMathType } from '~/types'

import { buildWebVitalsAttributionQuery } from './webVitalsAttribution'

describe('buildWebVitalsAttributionQuery', () => {
    it('groups INP by interaction target and type for the path', () => {
        const query = buildWebVitalsAttributionQuery({
            metric: 'INP',
            percentile: PropertyMathType.P90,
            path: '/pricing',
            isPathCleaningEnabled: false,
            pathCleaningFilters: undefined,
        })

        expect(query).toContain('properties.$web_vitals_INP_event.attribution.interactionTarget AS "Element"')
        expect(query).toContain('properties.$web_vitals_INP_event.attribution.interactionType AS "Interaction"')
        expect(query).toContain('countIf(toFloat(properties.$web_vitals_INP_value) > 200) AS "Above 200ms"')
        expect(query).toContain('quantile(0.9)(toFloat(properties.$web_vitals_INP_value))')
        expect(query).toContain("properties.$pathname = '/pricing'")
        expect(query).toContain('GROUP BY "Element", "Interaction"')
    })

    it('matches the cleaned path when path cleaning is on', () => {
        const query = buildWebVitalsAttributionQuery({
            metric: 'LCP',
            percentile: PropertyMathType.P75,
            path: '/project/<id>',
            isPathCleaningEnabled: true,
            pathCleaningFilters: [{ regex: '/project/\\d+', alias: '/project/<id>' }],
        })

        expect(query).toContain(
            "replaceRegexpAll(properties.$pathname, '/project/\\\\d+', '/project/<id>') = '/project/<id>'"
        )
    })

    it('returns null for metrics without element attribution', () => {
        expect(
            buildWebVitalsAttributionQuery({
                metric: 'FCP',
                percentile: PropertyMathType.P75,
                path: '/',
                isPathCleaningEnabled: false,
                pathCleaningFilters: undefined,
            })
        ).toBeNull()
    })
})
