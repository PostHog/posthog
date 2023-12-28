import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ExternalDataSourceType } from '~/types'

import { dataWarehouseTableLogic } from '../new_table/dataWarehouseTableLogic'
import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import type { sourceModalLogicType } from './sourceModalLogicType'

export const getHubspotRedirectUri = (): string => `${window.location.origin}/data-warehouse/settings/hubspot`
export interface ConnectorConfigType {
    name: ExternalDataSourceType
    fields: string[]
    caption: string
    disabledReason: string | null
}

// TODO: add icon
export const CONNECTORS: ConnectorConfigType[] = [
    {
        name: 'Stripe',
        fields: ['account_id', 'client_secret'],
        caption: 'Enter your Stripe credentials to link your Stripe to PostHog',
        disabledReason: null,
    },
    {
        name: 'Hubspot',
        fields: [],
        caption: '',
        disabledReason: null,
    },
]

export const sourceModalLogic = kea<sourceModalLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceModalLogic']),
    actions({
        selectConnector: (connector: ConnectorConfigType | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        onClear: true,
    }),
    connect({
        values: [
            dataWarehouseTableLogic,
            ['tableLoading'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
            preflightLogic,
            ['preflight'],
        ],
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
        addToHubspotButtonUrl: [
            (s) => [s.preflight],
            (preflight) => {
                return () => {
                    const clientId = preflight?.data_warehouse_integrations?.hubspot.client_id

                    if (!clientId) {
                        return null
                    }

                    const scopes = ['crm.objects.contacts.read', 'crm.objects.companies.read']

                    const params = new URLSearchParams()
                    params.set('client_id', clientId)
                    params.set('redirect_uri', getHubspotRedirectUri())
                    params.set('scope', scopes.join(' '))

                    return `https://app.hubspot.com/oauth/authorize?${params.toString()}`
                }
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/integrations/:kind/redirect': ({ kind = '' }, searchParams) => {
            actions.handleRedirect(kind, searchParams)
        },
    })),
    listeners(({ actions }) => ({
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'hubspot': {
                    try {
                        await api.externalDataSources.create({
                            source_type: 'Hubspot',
                            prefix: 'hubspot_',
                            payload: {
                                code: searchParams.get('code'),
                            },
                        })
                        lemonToast.success(`Oauth successful.`)
                    } catch (e) {
                        lemonToast.error(`Something went wrong. Please try again.`)
                    } finally {
                        router.actions.replace(urls.dataWarehouseSettings())
                    }
                    return
                }
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },
        onClear: () => {
            actions.selectConnector(null)
            actions.toggleManualLinkFormVisible(false)
            actions.resetTable()
        },
    })),
])
