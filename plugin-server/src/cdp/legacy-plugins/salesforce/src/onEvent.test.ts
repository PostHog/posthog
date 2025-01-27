import { PluginEvent } from '@posthog/plugin-scaffold'
import { shouldSendEvent, SalesforcePluginConfig, SalesforcePluginGlobal, SalesforcePluginMeta } from '.'

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

    it('adds the event with v1 mapping that matches', async () => {
        config.eventsToInclude = 'test'

        const res = await shouldSendEvent({ event: 'test' } as PluginEvent, { config } as SalesforcePluginMeta)
        expect(res).toBeTruthy()
    })

    it('skips the event with v1 mapping that does not match', async () => {
        config.eventsToInclude = 'to match'

        const res = await shouldSendEvent({ event: 'not to match' } as PluginEvent, { config } as SalesforcePluginMeta)
        expect(res).toBeFalsy()
    })

    it('adds the event with v2 mapping that matches', async () => {
        config.eventsToInclude = ''
        config.eventPath = ''
        config.eventEndpointMapping = JSON.stringify({ test: { salesforcePath: '/test', method: 'POST' } })

        const res = await shouldSendEvent({ event: 'test' } as PluginEvent, { config } as SalesforcePluginMeta)
        expect(res).toBeTruthy()
    })

    it('skips the event with v2 mapping that does not match', async () => {
        config.eventsToInclude = ''
        config.eventPath = ''
        config.eventEndpointMapping = JSON.stringify({ 'to match': { salesforcePath: '/test', method: 'POST' } })

        const res = await shouldSendEvent({ event: 'not to match' } as PluginEvent, { config } as SalesforcePluginMeta)
        expect(res).toBeFalsy()
    })
})
