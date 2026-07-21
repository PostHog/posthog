import { ApiError } from 'lib/api'

import { billingAlertSaveErrorMessage, billingAlertWritePayload, formErrorsFromApiError } from './billingAlertFormLogic'

describe('billing alert form server errors', () => {
    it('maps DRF field errors onto the form', () => {
        const error = new ApiError('Bad request', 400, undefined, {
            name: ['Ensure this field has no more than 160 characters.'],
            threshold_percentage: ['A valid number is required.'],
        })

        expect(formErrorsFromApiError(error)).toEqual({
            name: 'Ensure this field has no more than 160 characters.',
            thresholdPercentage: 'A valid number is required.',
        })
    })

    it('sends pending destinations in the atomic configuration write', () => {
        const payload = billingAlertWritePayload(
            {
                name: 'Daily spend',
                description: '',
                enabled: true,
                thresholdType: 'relative_increase',
                thresholdPercentage: 50,
                thresholdValue: 100,
                minimumValue: 0,
                baselineWindowDays: 7,
                evaluationDelayHours: 6,
                cooldownHours: 24,
            },
            [
                {
                    key: 'webhook',
                    label: 'Webhook',
                    payload: { type: 'webhook', webhook_url: 'https://example.com/alerts' },
                },
            ]
        )

        expect(payload.enabled).toBe(true)
        expect(payload.destination_changes).toEqual({
            create: [{ type: 'webhook', webhook_url: 'https://example.com/alerts' }],
        })
    })

    it('surfaces nested destination validation instead of a generic transport error', () => {
        const error = new ApiError('Bad request', 400, undefined, {
            destination_changes: {
                create: [{ webhook_url: ['Enter a supported Microsoft Teams webhook URL.'] }],
            },
        })

        expect(billingAlertSaveErrorMessage(error)).toBe('Enter a supported Microsoft Teams webhook URL.')
    })
})
