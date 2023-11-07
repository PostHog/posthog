import { actions, connect, kea, path, reducers, selectors, listeners } from 'kea'

import type { sourceModalLogicType } from './sourceModalLogicType'
import { forms } from 'kea-forms'
import { ExternalDataStripeSourceCreatePayload } from '~/types'
import api from 'lib/api'
import { lemonToast } from '@posthog/lemon-ui'
import { dataWarehouseTableLogic } from '../new_table/dataWarehouseTableLogic'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'

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
            defaults: { account_id: '', client_secret: '' } as ExternalDataStripeSourceCreatePayload,
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
        submitExternalDataSourceFailure: () => {
            lemonToast.error('Error creating new Data Resource. Check that provided credentials are valid.')
        },
    })),
])
