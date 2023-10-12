import { kea, path } from 'kea'

import type { sourceModalLogicType } from './sourceModalLogicType'
import { forms } from 'kea-forms'
import { AirbyteStripeResourceCreatePayload } from '~/types'
import api from 'lib/api'
import { lemonToast } from '@posthog/lemon-ui'

export const sourceModalLogic = kea<sourceModalLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceModalLogic']),
    forms(() => ({
        airbyteResource: {
            defaults: { account_id: '', client_secret: '' } as AirbyteStripeResourceCreatePayload,
            errors: ({ account_id, client_secret }) => {
                return {
                    account_id: !account_id && 'Please enter an account id.',
                    client_secret: !client_secret && 'Please enter a client secret.',
                }
            },
            submit: async (payload: AirbyteStripeResourceCreatePayload) => {
                const newResource = await api.airbyteResources.create(payload)
                lemonToast.success('New Data Resource Created')
                return newResource
            },
        },
    })),
])
