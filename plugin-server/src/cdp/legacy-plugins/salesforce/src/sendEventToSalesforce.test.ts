import { PluginEvent } from '@posthog/plugin-scaffold'
import { SalesforcePluginConfig, SalesforcePluginMeta, sendEventToSalesforce } from '.'

const mockFetch = jest.fn()
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(global as any).fetch = mockFetch

describe('sendEventsToSalesforce', () => {
    const global = { logger: { error: jest.fn(), debug: jest.fn() } }
    let config: SalesforcePluginConfig

    beforeEach(() => {
        mockFetch.mockClear()
        mockFetch.mockReturnValue(Promise.resolve({ status: 200 }))

        config = {
            salesforceHost: 'https://test.salesforce.com',
            eventMethodType: 'POST',
        } as SalesforcePluginConfig
    })

    it('can send an event to salesforce', async () => {
        config = {
            ...config,
            eventsToInclude: '$pageview,checkout',
            eventPath: 'test',
        } as SalesforcePluginConfig

        await sendEventToSalesforce(
            ({ event: '$pageview', properties: { $current_url: 'https://home/io' } } as unknown) as PluginEvent,
            ({ config, global } as unknown) as SalesforcePluginMeta,
            'token'
        )

        expect(mockFetch).toHaveBeenCalledWith('https://test.salesforce.com/test', {
            body: '{"$current_url":"https://home/io"}',
            headers: { Authorization: 'Bearer token', 'Content-Type': 'application/json' },
            method: 'POST',
        })
    })

    it('can send an event to salesforce', async () => {
        config = {
            ...config,
            eventsToInclude: '$pageview,checkout',
            eventPath: 'test',
        } as SalesforcePluginConfig

        await sendEventToSalesforce(
            ({ event: 'should not send', properties: { $current_url: 'https://home/io' } } as unknown) as PluginEvent,
            ({ config, global } as unknown) as SalesforcePluginMeta,
            'token'
        )

        expect(mockFetch).not.toHaveBeenCalled()
    })
})
