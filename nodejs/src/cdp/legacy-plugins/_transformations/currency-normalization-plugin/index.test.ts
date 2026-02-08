import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            $current_url: 'http://www.google.com',
            ...event.properties,
        },
        ...event,
    }) as unknown as PluginEvent

describe('currency normalization plugin', () => {
    const meta: LegacyTransformationPluginMeta = {} as any
    beforeEach(() => {
        meta.config = {
            openExchangeRatesApiKey: 'API_KEY',
            normalizedCurrency: 'EUR',
            amountProperty: 'amount',
            currencyProperty: 'currency',
            normalizedAmountProperty: 'normalized_amount',
            normalizedCurrencyProperty: 'normalized_currency',
        }
    })
    test('changes nothing for $pageview events', () => {
        const pageviewEvent = createEvent({ event: '$pageview' })
        const processedPageviewEvent = processEvent(pageviewEvent, meta)
        expect(processedPageviewEvent).toEqual(pageviewEvent)
    })

    test('changes nothing for $identify events', () => {
        const identifyEvent = createEvent({ event: '$identify' })
        const processedIdentifyEvent = processEvent(identifyEvent, meta)
        expect(processedIdentifyEvent).toEqual(identifyEvent)
    })

    test('normalizes currency on events', () => {
        const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'PLN' } })
        const processedCurrencyEvent = processEvent(currencyEvent, meta)
        expect(processedCurrencyEvent).toEqual({
            ...currencyEvent,
            properties: { ...currencyEvent.properties, normalized_amount: 4.7536, normalized_currency: 'EUR' },
        })
    })

    test('bails if does not know the currency', () => {
        const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'ABC' } })
        const processedCurrencyEvent = processEvent(currencyEvent, meta)
        expect(processedCurrencyEvent).toEqual(currencyEvent)
    })

    test('bails if no API key found', () => {
        const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'USD' } })
        meta.config.openExchangeRatesApiKey = null
        const processedCurrencyEvent = processEvent(currencyEvent, meta)
        expect(processedCurrencyEvent).toEqual(currencyEvent)
    })
})
