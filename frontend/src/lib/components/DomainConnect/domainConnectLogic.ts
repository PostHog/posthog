import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { DomainConnectProviderName } from '~/queries/schema/schema-general'

import type { domainConnectLogicType } from './domainConnectLogicType'

export interface DomainConnectProvider {
    endpoint: string
    name: DomainConnectProviderName
}

export interface DomainConnectInfo {
    supported: boolean
    provider_name: DomainConnectProviderName | null
    available_providers: DomainConnectProvider[]
}

export interface DomainConnectLogicProps {
    /** Unique key to prevent state sharing between instances (not `key` because React strips it) */
    logicKey: string
    /** The domain to check Domain Connect support for */
    domain: string | null
    /** Which resource type this Domain Connect flow is for */
    context: 'email' | 'proxy'
    /** Required when context is 'email' */
    integrationId?: number
    /** Required when context is 'proxy' */
    proxyRecordId?: string
}

export const domainConnectLogic = kea<domainConnectLogicType>([
    path((key) => ['lib', 'components', 'DomainConnect', 'domainConnectLogic', key]),
    props({} as DomainConnectLogicProps),
    key(({ logicKey }) => logicKey),
    actions({
        openDomainConnect: (providerEndpoint?: string) => ({ providerEndpoint }),
        checkDomain: true,
    }),
    loaders(({ props }) => ({
        domainConnectInfo: {
            checkDomain: async (): Promise<DomainConnectInfo | null> => {
                if (!props.domain) {
                    return null
                }
                return api.integrations.domainConnectCheck(props.domain)
            },
        },
    })),
    selectors({
        autoDetected: [
            (s) => [s.domainConnectInfo],
            (info: DomainConnectInfo | null): boolean => {
                return info?.supported === true
            },
        ],
        providerName: [
            (s) => [s.domainConnectInfo],
            (info: DomainConnectInfo | null): DomainConnectProviderName | null => {
                return info?.provider_name ?? null
            },
        ],
        availableProviders: [
            (s) => [s.domainConnectInfo],
            (info: DomainConnectInfo | null): DomainConnectProvider[] => {
                return info?.available_providers ?? []
            },
        ],
        hasAnyOption: [
            (s) => [s.autoDetected, s.availableProviders],
            (autoDetected: boolean, providers: DomainConnectProvider[]): boolean => {
                return autoDetected || providers.length > 0
            },
        ],
    }),
    listeners(({ props }) => ({
        openDomainConnect: async ({ providerEndpoint }) => {
            const currentUrl = window.location.href.split('?')[0]
            const redirectUri = `${currentUrl}?domain_connect=${props.context}`

            try {
                const { url } = await api.integrations.domainConnectApplyUrl({
                    context: props.context,
                    integration_id: props.integrationId,
                    proxy_record_id: props.proxyRecordId,
                    redirect_uri: redirectUri,
                    provider_endpoint: providerEndpoint,
                })
                window.open(url, '_blank', 'noopener,noreferrer')
            } catch (e) {
                if (e instanceof ApiError) {
                    lemonToast.error(`Failed to generate Domain Connect URL: ${e.detail || 'Please try again.'}`)
                } else {
                    lemonToast.error('Failed to generate Domain Connect URL. Please configure DNS manually.')
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.domain) {
            actions.checkDomain()
        }

        // Handle return from Domain Connect redirect
        const searchParams = new URLSearchParams(window.location.search)
        if (searchParams.get('domain_connect') === props.context) {
            const url = new URL(window.location.href)
            url.searchParams.delete('domain_connect')
            router.actions.replace(url.pathname + url.search)
        }
    }),
])
