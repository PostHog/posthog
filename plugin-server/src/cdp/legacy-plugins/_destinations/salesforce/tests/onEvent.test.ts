import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { SalesforceMeta, SalesforcePluginConfig, shouldSendEvent } from '../index'

describe('onEvent', () => {
    let config: SalesforcePluginConfig

    beforeEach(() => {
        config = {
            salesforceHost: 'https://example.io',
            eventPath: 'test',
            eventMethodType: 'test',
            username: 'test',
            password: 'test',
            consumerKey: 'test',
            consumerSecret: 'test',
            eventsToInclude: '$pageview',
            propertiesToInclude: '',
            eventEndpointMapping: '',
            debugLogging: '',
        }
    })

    it('adds the event with v1 mapping that matches', () => {
        config.eventsToInclude = 'test'

        const res = shouldSendEvent({ event: 'test' } as ProcessedPluginEvent, { config } as SalesforceMeta)
        expect(res).toBeTruthy()
    })

    it('skips the event with v1 mapping that does not match', () => {
        config.eventsToInclude = 'to match'

        const res = shouldSendEvent({ event: 'not to match' } as ProcessedPluginEvent, { config } as SalesforceMeta)
        expect(res).toBeFalsy()
    })

    it('adds the event with v2 mapping that matches', () => {
        config.eventsToInclude = ''
        config.eventPath = ''
        config.eventEndpointMapping = JSON.stringify({ test: { salesforcePath: '/test', method: 'POST' } })

        const res = shouldSendEvent({ event: 'test' } as ProcessedPluginEvent, { config } as SalesforceMeta)
        expect(res).toBeTruthy()
    })

    it('skips the event with v2 mapping that does not match', () => {
        config.eventsToInclude = ''
        config.eventPath = ''
        config.eventEndpointMapping = JSON.stringify({ 'to match': { salesforcePath: '/test', method: 'POST' } })

        const res = shouldSendEvent({ event: 'not to match' } as ProcessedPluginEvent, { config } as SalesforceMeta)
        expect(res).toBeFalsy()
    })
})
