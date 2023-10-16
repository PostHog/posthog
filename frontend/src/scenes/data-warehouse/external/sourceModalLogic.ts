import { actions, kea, path, reducers, selectors } from 'kea'

import type { sourceModalLogicType } from './sourceModalLogicType'
import { forms } from 'kea-forms'
import { AirbyteStripeResourceCreatePayload } from '~/types'
import api from 'lib/api'
import { lemonToast } from '@posthog/lemon-ui'

export interface ConnectorConfigType {
    name: string
    fields: string[]
}

// TODO: add icon
export const CONNECTORS: ConnectorConfigType[] = [
    {
        name: 'Stripe',
        fields: ['accound_id', 'client_secret'],
    },
]

export const sourceModalLogic = kea<sourceModalLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceModalLogic']),
    actions({
        selectConnector: (connector: ConnectorConfigType | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
    }),
    reducers({
        selectedConnector: [
            null as ConnectorConfigType | null,
            {
                selectConnector: (_, { connector }) => connector,
            },
        ],
        isManualLinkFormVisible: [
            false,
            {
                toggleManualLinkFormVisible: (_, { visible }) => visible,
            },
        ],
    }),
    selectors({
        showFooter: [
            (s) => [s.selectedConnector, s.isManualLinkFormVisible],
            (selectedConnector, isManualLinkFormVisible) => selectedConnector || isManualLinkFormVisible,
        ],
    }),
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
