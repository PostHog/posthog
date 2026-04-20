import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const currencyNormalizationPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-currency-normalization-plugin',
        name: 'Currency normalization',
        description: 'Normalizes currency amounts. NOTE: This plugin is deprecated.',
        icon_url: 'https://raw.githubusercontent.com/posthog/currency-normalization-plugin/main/logo.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'openExchangeRatesApiKey',
                label: 'OpenExchangeRates API Key',
                type: 'string',
                default: '',
                required: true,
            },
            {
                key: 'normalizedCurrency',
                label: 'Currency to normalise to (e.g. "EUR")',
                type: 'string',
                default: '',
                required: true,
            },
            {
                key: 'amountProperty',
                label: 'Property key for the amount',
                type: 'string',
                default: 'amount',
                required: true,
            },
            {
                key: 'currencyProperty',
                label: 'Property key for the currency',
                type: 'string',
                default: 'currency',
                required: true,
            },
            {
                key: 'normalizedAmountProperty',
                label: 'Property key for the normalized amount',
                type: 'string',
                default: 'normalized_amount',
                required: true,
            },
            {
                key: 'normalizedCurrencyProperty',
                label: 'Property key for the normalized currency',
                type: 'string',
                default: 'normalized_currency',
                required: true,
            },
        ],
    },
}
