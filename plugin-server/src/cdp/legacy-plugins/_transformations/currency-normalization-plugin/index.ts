import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import DATA from './rates.json'

const RATES = DATA.rates as Record<string, number>

export function processEvent(event: PluginEvent, meta: LegacyTransformationPluginMeta) {
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
        const amount = event.properties[amountProperty]
        const currency = event.properties[currencyProperty]

        if (RATES[currency] && RATES[normalizedCurrency]) {
            const normalizedAmount = roundToDigits((amount * RATES[normalizedCurrency]) / RATES[currency], 4)
            event.properties[normalizedAmountProperty] = normalizedAmount
            event.properties[normalizedCurrencyProperty] = normalizedCurrency
        }
    }

    return event
}

function roundToDigits(number: number, digits: number) {
    return Math.round(number * Math.pow(10, digits)) / Math.pow(10, digits)
}
