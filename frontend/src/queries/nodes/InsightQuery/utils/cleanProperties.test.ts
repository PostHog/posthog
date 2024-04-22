import { cleanEntityProperties, cleanGlobalProperties } from './cleanProperties'

describe('cleanGlobalProperties', () => {
    it('handles empty properties', () => {
        const properties = {}

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual(undefined)
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

    it('handles property group filters values', () => {
        const properties = {
            type: 'AND',
            values: [{ key: 'id', type: 'cohort', value: 850, operator: null }],
        }

        const result = cleanGlobalProperties(properties)

        expect(result).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [{ key: 'id', type: 'cohort', value: 850 }],
                },
            ],
        })
    })
})

describe('cleanEntityProperties', () => {
    it('handles empty properties', () => {
        const properties = {}

        const result = cleanEntityProperties(properties)

        expect(result).toEqual(undefined)
    })

    it('handles old style properties', () => {
        const properties = { utm_medium__icontains: 'email' }

        const result = cleanEntityProperties(properties)

        expect(result).toEqual([
            {
                key: 'utm_medium',
                operator: 'icontains',
                type: 'event',
                value: 'email',
            },
        ])
    })

    it('handles property filter lists', () => {
        const properties = [
            { key: '$current_url', type: 'event', value: 'https://hedgebox.net/signup/', operator: 'exact' },
        ]

        const result = cleanEntityProperties(properties)

        expect(result).toEqual(properties)
    })

    it('handles property group values', () => {
        const properties = {
            type: 'AND',
            values: [
                {
                    key: '$current_url',
                    operator: 'exact',
                    type: 'event',
                    value: 'https://hedgebox.net/signup/',
                },
            ],
        }

        const result = cleanEntityProperties(properties)

        expect(result).toEqual([
            {
                key: '$current_url',
                operator: 'exact',
                type: 'event',
                value: 'https://hedgebox.net/signup/',
            },
        ])
    })
})
