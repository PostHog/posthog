async function setupPlugin(meta) {
    const apiKey = meta.config['openExchangeRatesApiKey'] || null

    if (apiKey) {
        await fetchRatesIfNeeded(meta)
    } else {
        throw new Error('No API key found!')
    }
}

async function processEvent(event, meta) {
    const {
        openExchangeRatesApiKey,
        normalizedCurrency,
        amountProperty,
        currencyProperty,
        normalizedAmountProperty,
        normalizedCurrencyProperty,
    } = meta.config

    if (
        openExchangeRatesApiKey &&
        normalizedCurrency &&
        event?.properties &&
        typeof event.properties[amountProperty] !== 'undefined' &&
        typeof event.properties[currencyProperty] !== 'undefined'
    ) {
        await fetchRatesIfNeeded(meta)
        const rates = await meta.cache.get('currency_rates')

        if (rates) {
            const amount = event.properties[amountProperty]
            const currency = event.properties[currencyProperty]

            if (rates[currency] && rates[normalizedCurrency]) {
                const normalizedAmount = roundToDigits((amount * rates[normalizedCurrency]) / rates[currency], 4)
                event.properties[normalizedAmountProperty] = normalizedAmount
                event.properties[normalizedCurrencyProperty] = normalizedCurrency
            }
        }
    }

    return event
}

module.exports = {
    setupPlugin,
    processEvent,
    schedule: {
        hourly: [fetchRatesIfNeeded],
    },
    webHooks: {
        fetchRates,
    },
}

// Internal library functions below

async function fetchRatesIfNeeded(meta) {
    const currencyRatesFetchedAt = await meta.cache.get('currency_rates_fetched_at')
    if (!currencyRatesFetchedAt || currencyRatesFetchedAt < new Date().getTime() - 86400 * 1000) {
        // 24h
        await fetchRates(meta)
    }
}

async function fetchRates({ config, cache }) {
    try {
        const url = `https://openexchangerates.org/api/latest.json?app_id=${config['openExchangeRatesApiKey']}`
        const response = await fetch(url, { timeout: 1000 })
        const json = await response.json()

        if (json && json['rates']) {
            cache.set('currency_rates', json['rates'])
            cache.set('currency_rates_fetched_at', new Date().getTime())
        } else {
            throw new Error('Error fetching currency rates!')
        }
    } catch (e) {
        throw new Error('Error fetching currency rates!')
    }
}

function roundToDigits(number, digits) {
    return Math.round(number * Math.pow(10, digits)) / Math.pow(10, digits)
}
