import { PluginEvent } from '@posthog/plugin-scaffold'
import {
    EventSink,
    EventToSinkMapping,
    parseEventSinkConfig,
    SalesforcePluginConfig,
    SalesforcePluginMeta,
    sendEventToSalesforce,
    verifyConfig,
} from '.'

const mockFetch = jest.fn()
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(global as any).fetch = mockFetch

describe('event sink mapping', () => {
    const invalidMapping: EventToSinkMapping = {
        a: {
            salesforcePath: 'something',
            propertiesToInclude: '',
            method: 'POST',
        },
        b: {
            salesforcePath: '', // invalid because it does not have a salesforce path
            propertiesToInclude: '',
            method: 'POST',
        },
    }

    const missingMethodInvalidMapping: EventToSinkMapping = {
        a: {
            salesforcePath: 'something',
            propertiesToInclude: '',
        } as EventSink,
    }

    const validMapping: EventToSinkMapping = {
        $pageview: {
            salesforcePath: 'something',
            propertiesToInclude: 'one,two,three',
            method: 'POST',
        },
    }

    describe('parsing', () => {
        it('can parse a valid event sink mapping', () => {
            const config = ({ eventEndpointMapping: JSON.stringify(validMapping) } as unknown) as SalesforcePluginConfig
            const mapping = parseEventSinkConfig(config)
            expect(mapping).toEqual(validMapping)
        })

        it('can parse an empty event sink mapping', () => {
            const config = ({ eventEndpointMapping: '' } as unknown) as SalesforcePluginConfig
            const mapping = parseEventSinkConfig(config)
            expect(mapping).toEqual(null)
        })

        it('can parse nonsense as an empty event sink mapping', () => {
            const config = ({ eventEndpointMapping: '🤘' } as unknown) as SalesforcePluginConfig
            expect(() => parseEventSinkConfig(config)).toThrowError(
                'eventEndpointMapping must be an empty string or contain valid JSON!',
            )
        })
    })

    describe('validation', () => {
        it('can validate an event sink mapping with missing salesforcePath', () => {
            expect(() => {
                verifyConfig(({
                    config: {
                        eventEndpointMapping: JSON.stringify(invalidMapping),
                    },
                } as unknown) as SalesforcePluginMeta)
            }).toThrowError('You must provide a salesforce path for each mapping in config.eventEndpointMapping.')
        })

        it('can validate an event sink mapping with missing method', () => {
            expect(() => {
                verifyConfig(({
                    config: {
                        eventEndpointMapping: JSON.stringify(missingMethodInvalidMapping),
                    },
                } as unknown) as SalesforcePluginMeta)
            }).toThrowError('You must provide a method for each mapping in config.eventEndpointMapping.')
        })

        it('can validate invalid JSON in EventToSinkMapping', () => {
            const mapping = ({
                really: 'not an event to sink mapping',
            } as unknown) as EventToSinkMapping
            expect(() => {
                verifyConfig(({
                    config: {
                        eventEndpointMapping: JSON.stringify(mapping),
                    },
                } as unknown) as SalesforcePluginMeta)
            }).toThrowError('You must provide a salesforce path for each mapping in config.eventEndpointMapping.')
        })

        it('can validate eventsToInclude must be present if an event sink mapping is not', () => {
            expect(() => {
                verifyConfig(({
                    config: {
                        eventEndpointMapping: '',
                    },
                } as unknown) as SalesforcePluginMeta)
            }).toThrowError('If you are not providing an eventEndpointMapping then you must provide events to include.')
        })

        it('can validate that you should not send v1 and v2 config', () => {
            const mapping: EventToSinkMapping = {
                $pageView: {
                    salesforcePath: 'something',
                    propertiesToInclude: '',
                    method: 'POST',
                },
            }
            expect(() => {
                verifyConfig(({
                    config: {
                        eventEndpointMapping: JSON.stringify(mapping),
                        eventsToInclude: '$pageView',
                    },
                } as unknown) as SalesforcePluginMeta)
            }).toThrowError('You should not provide both eventsToInclude and eventMapping.')
        })
    })

    describe('sending to sink', () => {
        const global = ({
            logger: {
                debug: jest.fn(),
                error: jest.fn(),
            },
        } as unknown) as SalesforcePluginMeta['global']
        const config = {
            salesforceHost: 'https://example.io',
            eventMethodType: 'POST',
            eventPath: '',
            username: '',
            password: '',
            consumerKey: '',
            consumerSecret: '',
            eventsToInclude: '',
            debugLogging: 'false',
            eventEndpointMapping: JSON.stringify(validMapping),
        }

        beforeEach(() => {
            mockFetch.mockClear()
            mockFetch.mockReturnValue(Promise.resolve({ status: 200 }))
        })

        it('does not send to a sink if there is no mapping for the event', async () => {
            await sendEventToSalesforce(
                { event: 'uninteresting' } as PluginEvent,
                ({ config, global } as unknown) as SalesforcePluginMeta,
                'token',
            )
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('does send to a sink if there is a mapping for the event', async () => {
            await sendEventToSalesforce(
                ({
                    event: '$pageview',
                    properties: { unwanted: 'excluded', two: 'includes' },
                } as unknown) as PluginEvent,
                ({
                    global: global,
                    config: config,
                    cache: undefined,
                } as unknown) as SalesforcePluginMeta,
                'the bearer token',
            )
            expect(mockFetch).toHaveBeenCalledWith('https://example.io/something', {
                body: '{"two":"includes"}',
                headers: { Authorization: 'Bearer the bearer token', 'Content-Type': 'application/json' },
                method: 'POST',
            })
        })
    })
})
