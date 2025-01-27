const {
    createEvent,
    createIdentify,
    createPageview,
    createCache,
    getMeta,
    resetMeta,
    clone,
} = require('posthog-plugins/test/utils.js')
const { setupPlugin, processEvent } = require('../index')
const rates = require('./rates.json')

global.fetch = jest.fn(async () => ({
    json: async () => rates,
}))

beforeEach(() => {
    fetch.mockClear()

    resetMeta({
        config: {
            openExchangeRatesApiKey: 'API_KEY',
            normalizedCurrency: 'EUR',
            amountProperty: 'amount',
            currencyProperty: 'currency',
            normalizedAmountProperty: 'normalized_amount',
            normalizedCurrencyProperty: 'normalized_currency',
        },
    })
})

test('setupPlugin', async () => {
    expect(fetch).toHaveBeenCalledTimes(0)

    await setupPlugin(getMeta())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('https://openexchangerates.org/api/latest.json?app_id=API_KEY')

    await setupPlugin(getMeta())
    expect(fetch).toHaveBeenCalledTimes(1)

    // clear the cache and try again:
    getMeta().cache = createCache()

    await setupPlugin(getMeta())
    expect(fetch).toHaveBeenCalledTimes(2)

    // clear the cache and try again:
    getMeta().cache = createCache()
    getMeta().config.openExchangeRatesApiKey = ''

    await expect(setupPlugin(getMeta())).rejects.toThrow('No API key found!')
})

test('changes nothing for $pageview events', async () => {
    const pageviewEvent = createPageview()
    const processedPageviewEvent = await processEvent(clone(pageviewEvent), getMeta())
    expect(processedPageviewEvent).toEqual(pageviewEvent)
    expect(fetch).toHaveBeenCalledTimes(0)
})

test('changes nothing for $identify events', async () => {
    const identifyEvent = createIdentify()
    const processedIdentifyEvent = await processEvent(clone(identifyEvent), getMeta())
    expect(processedIdentifyEvent).toEqual(identifyEvent)
    expect(fetch).toHaveBeenCalledTimes(0)
})

test('fetches rates if none found', async () => {
    const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'PLN' } })

    await processEvent(clone(currencyEvent), getMeta())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('https://openexchangerates.org/api/latest.json?app_id=API_KEY')

    await processEvent(clone(currencyEvent), getMeta())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('https://openexchangerates.org/api/latest.json?app_id=API_KEY')
})

test('normalizes currency on events', async () => {
    const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'PLN' } })
    const processedCurrencyEvent = await processEvent(clone(currencyEvent), getMeta())
    expect(processedCurrencyEvent).toEqual({
        ...currencyEvent,
        properties: { ...currencyEvent.properties, normalized_amount: 4.4691, normalized_currency: 'EUR' },
    })
})

test('bails if does not know the currency', async () => {
    const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'ABC' } })
    const processedCurrencyEvent = await processEvent(clone(currencyEvent), getMeta())
    expect(processedCurrencyEvent).toEqual(currencyEvent)
})

test('bails if no API key found', async () => {
    const currencyEvent = createEvent({ event: 'booking completed', properties: { amount: '20', currency: 'USD' } })
    getMeta().config.openExchangeRatesApiKey = null
    const processedCurrencyEvent = await processEvent(clone(currencyEvent), getMeta())
    expect(processedCurrencyEvent).toEqual(currencyEvent)
})
