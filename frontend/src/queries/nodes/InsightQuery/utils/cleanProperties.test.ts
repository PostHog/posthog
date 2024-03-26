import { cleanGlobalProperties } from './cleanProperties'

describe('cleanGlobalProperties', () => {
    it('handles property filter lists', () => {
        const properties = [{ key: 'id', type: 'cohort', value: 636, operator: null }]

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual({
            type: 'AND',
            values: [{ type: 'AND', values: [{ key: 'id', type: 'cohort', value: 636 }] }],
        })
    })

    it('handles property group filters', () => {
        const properties = {
            type: 'AND',
            values: [{ type: 'AND', values: [{ key: 'id', type: 'cohort', value: 850, operator: null }] }],
        }

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual(properties)
    })

    it('handles property group filters without nested property group filter values', () => {
        const properties = {
            type: 'AND',
            values: [{ key: 'id', type: 'cohort', value: 850, operator: null }],
        }

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual(properties)
    })

    it('handles old style properties', () => {
        const properties = { utm_medium__icontains: 'email' }

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [
                        {
                            key: 'utm_medium',
                            operator: 'icontains',
                            type: 'event',
                            value: 'email',
                        },
                    ],
                },
            ],
        })
    })
})

describe('cleanEntityProperties', () => {})
