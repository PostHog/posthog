const { createEvent } = require('@posthog/plugin-scaffold/test/utils.js')
const { processEvent } = require('./index')

const nestedEventProperties = {
    a: {
        b: {
            c: {
                d: {
                    e: {
                        f: 'nested under e',
                    },
                    z: 'nested under d',
                },
                z: 'nested under c',
            },
            z: 'nested under b',
        },
        z: 'nested under a',
    },
    w: {
        array: [{ z: 'nested in w array' }],
    },
    x: 'not nested',
    y: 'not nested either',
}

describe('the property flattener', () => {
    test('flattens all nested properties', async () => {
        const event = createEvent({ event: 'test', properties: nestedEventProperties })

        const eventsOutput = await processEvent(event, { config: { separator: '__' } })

        const expectedProperties = {
            a: nestedEventProperties.a,
            w: nestedEventProperties.w,
            x: 'not nested',
            y: 'not nested either',
            a__b__c__d__e__f: 'nested under e',
            a__b__c__d__z: 'nested under d',
            a__b__c__z: 'nested under c',
            a__b__z: 'nested under b',
            a__z: 'nested under a',
            w__array__0__z: 'nested in w array',
        }

        expect(eventsOutput).toEqual(createEvent({ event: 'test', properties: expectedProperties }))
    })

    test('autocapture is ignored', async () => {
        const event = createEvent({
            event: '$autocapture',
            properties: {
                $elements: [
                    { tag_name: 'span', nth_child: 1 },
                    { tag_name: 'div', nth_child: 1 },
                ],
                $elements_chain: 'span:nth_child="1";div:nth_child="1"',
            },
        })

        const eventsOutput = await processEvent(event, { config: { separator: '__' } })

        const expectedProperties = {
            $elements: [
                { tag_name: 'span', nth_child: 1 },
                { tag_name: 'div', nth_child: 1 },
            ],
            $elements_chain: 'span:nth_child="1";div:nth_child="1"',
        }

        expect(eventsOutput).toEqual(createEvent({ event: '$autocapture', properties: expectedProperties }))
    })

    test('organization usage report is ignored because it causes very many flattened properties', async () => {
        const event = createEvent({
            event: 'organization usage report',
            properties: {
                any: [{ nested: 'property' }],
            },
        })

        const eventsOutput = await processEvent(event, { config: { separator: '__' } })

        const expectedProperties = {
            any: [{ nested: 'property' }],
        }

        expect(eventsOutput).toEqual(
            createEvent({ event: 'organization usage report', properties: expectedProperties })
        )
    })

    test('set and set once', async () => {
        const event = createEvent({
            event: '$identify',
            properties: {
                $set: {
                    example: {
                        company_size: 20,
                        category: ['a', 'b'],
                    },
                },
                $set_once: {
                    example: {
                        company_size: 20,
                        category: ['a', 'b'],
                    },
                },
            },
        })

        const eventsOutput = await processEvent(event, { config: { separator: '__' } })

        const expectedProperties = {
            $set: {
                example: {
                    company_size: 20,
                    category: ['a', 'b'],
                },
                example__company_size: 20,
                example__category__0: 'a',
                example__category__1: 'b',
            },
            $set_once: {
                example: {
                    company_size: 20,
                    category: ['a', 'b'],
                },
                example__company_size: 20,
                example__category__0: 'a',
                example__category__1: 'b',
            },
        }

        expect(eventsOutput.properties).toEqual(expectedProperties)
    })

    test('$group_set', async () => {
        const event = createEvent({
            event: '$groupidentify',
            properties: {
                $group_set: {
                    a: 'shopify.com',
                    ads: {
                        'facebook-ads': true,
                        'google-ads': true,
                        'tiktok-ads': false,
                        'pinterest-ads': false,
                        'snapchat-ads': false,
                        fairing: false,
                        slack: false,
                    },
                    pixel: true,
                    pixel_settings: {
                        allow_auto_install: true,
                    },
                    currency: 'USD',
                    timezone: 'XXX',
                },
            },
        })

        const eventsOutput = await processEvent(event, { config: { separator: '__' } })

        const expectedProperties = {
            $group_set: {
                a: 'shopify.com',
                ads: {
                    'facebook-ads': true,
                    'google-ads': true,
                    'tiktok-ads': false,
                    'pinterest-ads': false,
                    'snapchat-ads': false,
                    fairing: false,
                    slack: false,
                },
                pixel: true,
                pixel_settings: {
                    allow_auto_install: true,
                },
                currency: 'USD',
                timezone: 'XXX',
                'ads__facebook-ads': true,
                ads__fairing: false,
                'ads__google-ads': true,
                'ads__pinterest-ads': false,
                ads__slack: false,
                'ads__snapchat-ads': false,
                'ads__tiktok-ads': false,
                pixel_settings__allow_auto_install: true,
            },
        }

        expect(eventsOutput.properties).toEqual(expectedProperties)
    })
})
