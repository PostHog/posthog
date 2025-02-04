import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { SalesforceMeta, SalesforcePluginConfig, sendEventToSalesforce } from '../index'

const mockFetch = jest.fn()

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
            { event: '$pageview', properties: { $current_url: 'https://home/io' } } as unknown as ProcessedPluginEvent,
            {
                config,
                global,
                logger: { error: jest.fn(), debug: jest.fn() },
                fetch: mockFetch as unknown,
            } as unknown as SalesforceMeta,
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
            {
                event: 'should not send',
                properties: { $current_url: 'https://home/io' },
            } as unknown as ProcessedPluginEvent,
            { config, global, logger: { error: jest.fn(), debug: jest.fn() } } as unknown as SalesforceMeta,
            'token'
        )

        expect(mockFetch).not.toHaveBeenCalled()
    })
})
