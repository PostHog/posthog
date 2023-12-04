import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { ExternalDataStripeSourceCreatePayload } from '~/types'

import { dataWarehouseTableLogic } from '../new_table/dataWarehouseTableLogic'
import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import type { sourceModalLogicType } from './sourceModalLogicType'

export interface ConnectorConfigType {
    name: string
    fields: string[]
    caption: string
    disabledReason: string | null
}

// TODO: add icon
export const CONNECTORS: ConnectorConfigType[] = [
    {
        name: 'Stripe',
        fields: ['accound_id', 'client_secret'],
        caption: 'Enter your Stripe credentials to link your Stripe to PostHog',
        disabledReason: null,
    },
]

export const sourceModalLogic = kea<sourceModalLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceModalLogic']),
    actions({
        selectConnector: (connector: ConnectorConfigType | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
    }),
    connect({
        values: [dataWarehouseTableLogic, ['tableLoading'], dataWarehouseSettingsLogic, ['dataWarehouseSources']],
        actions: [
            dataWarehouseSceneLogic,
            ['toggleSourceModal'],
            dataWarehouseTableLogic,
            ['resetTable'],
            dataWarehouseSettingsLogic,
            ['loadSources'],
        ],
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
        connectors: [
            (s) => [s.dataWarehouseSources],
            (sources) => {
                return CONNECTORS.map((connector) => ({
                    ...connector,
                    disabledReason:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? 'Already linked'
                            : null,
                }))
            },
        ],
    }),
    forms(() => ({
        externalDataSource: {
            defaults: {
                account_id: '',
                client_secret: '',
                prefix: '',
                source_type: 'Stripe',
            } as ExternalDataStripeSourceCreatePayload,
            errors: ({ account_id, client_secret }) => {
                return {
                    account_id: !account_id && 'Please enter an account id.',
                    client_secret: !client_secret && 'Please enter a client secret.',
                }
            },
            submit: async (payload: ExternalDataStripeSourceCreatePayload) => {
                const newResource = await api.externalDataSources.create(payload)
                return newResource
            },
        },
    })),
    listeners(({ actions }) => ({
        submitExternalDataSourceSuccess: () => {
            lemonToast.success('New Data Resource Created')
            actions.toggleSourceModal()
            actions.resetExternalDataSource()
            actions.loadSources()
            router.actions.push(urls.dataWarehouseSettings())
        },
        submitExternalDataSourceFailure: ({ error }) => {
            lemonToast.error(error?.message || 'Something went wrong')
        },
    })),
])
