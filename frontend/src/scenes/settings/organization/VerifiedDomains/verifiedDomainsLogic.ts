import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { SECURE_URL_REGEX } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { bindModalToUrl } from 'lib/logic/bindModalToUrl'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import {
    identityProviderConfigsCreate,
    identityProviderConfigsDestroy,
    identityProviderConfigsPartialUpdate,
    identityProviderConfigsScimTokenCreate,
} from '~/generated/core/api'
import { AvailableFeature, OrganizationDomainType, PaginatedSCIMRequestLogs } from '~/types'

import type { verifiedDomainsLogicType } from './verifiedDomainsLogicType'

/**
 * Resolve the `IdentityProviderConfig` id that backs a domain, creating and linking an empty
 * config first if the domain doesn't have one yet. The config is the source of truth for
 * SAML/SCIM/ID-JAG settings, so all IdP-config CRUD targets it rather than the domain.
 *
 * We link the (still empty) config to the domain *before* populating any fields, so the
 * domain→config mirror that runs on the link's domain save sees no divergence to clobber.
 * If linking fails, the freshly created config is deleted so we don't leave an orphan behind.
 */
async function ensureIdpConfigId(organizationId: string, domain: OrganizationDomainType): Promise<string> {
    if (domain.identity_provider_config) {
        return domain.identity_provider_config
    }
    const config = await identityProviderConfigsCreate(organizationId, { name: domain.domain })
    try {
        await api.update(`api/organizations/${organizationId}/domains/${domain.id}`, {
            identity_provider_config: config.id,
        })
    } catch (error) {
        await identityProviderConfigsDestroy(organizationId, config.id).catch(() => undefined)
        throw error
    }
    return config.id
}

/** Re-fetch a single domain and replace it in local state, reflecting reverse-synced IdP columns. */
async function refreshDomain(
    organizationId: string,
    domainId: string,
    replaceDomain: (domain: OrganizationDomainType) => void
): Promise<OrganizationDomainType> {
    const domain = await api.get<OrganizationDomainType>(`api/organizations/${organizationId}/domains/${domainId}`)
    replaceDomain(domain)
    return domain
}

export type OrganizationDomainUpdatePayload = Partial<
    Pick<OrganizationDomainType, 'jit_provisioning_enabled' | 'sso_enforcement'>
> &
    Pick<OrganizationDomainType, 'id'>

export type SAMLConfigType = Partial<
    Pick<OrganizationDomainType, 'saml_acs_url' | 'saml_entity_id' | 'saml_x509_cert'> &
        Pick<OrganizationDomainType, 'id'>
>

export type SCIMConfigType = Partial<
    Pick<OrganizationDomainType, 'scim_enabled' | 'scim_base_url' | 'scim_bearer_token'> &
        Pick<OrganizationDomainType, 'id'>
>

export type IdJagConfigType = Partial<
    Pick<OrganizationDomainType, 'id_jag_issuer_url' | 'id_jag_jwks_url' | 'id_jag_allowed_clients'> &
        Pick<OrganizationDomainType, 'id'>
>

export const isSecureURL = (url: string): boolean => {
    try {
        const parsed = new URL(url)
        return parsed.protocol === 'https:'
    } catch {
        return false
    }
}

export const verifiedDomainsLogic = kea<verifiedDomainsLogicType>([
    path(['scenes', 'organization', 'verifiedDomainsLogic']),
    connect(() => ({ values: [organizationLogic, ['currentOrganizationId']], logic: [userLogic] })),
    actions({
        replaceDomain: (domain: OrganizationDomainType) => ({ domain }),
        showAddDomainModal: true,
        hideAddDomainModal: true,
        setConfigureSAMLModalId: (id: string | null) => ({ id }),
        setConfigureSCIMModalId: (id: string | null) => ({ id }),
        setConfigureIdJagModalId: (id: string | null) => ({ id }),
        setScimLogsModalId: (id: string | null) => ({ id }),
        setScimLogsStatusFilter: (filter: 'all' | 'success' | '4xx' | '5xx') => ({ filter }),
        setScimLogsSearch: (search: string) => ({ search }),
        setScimLogsPage: (page: number) => ({ page }),
        reloadScimLogs: true,
        setVerifyModal: (id: string | null) => ({ id }),
    }),
    reducers({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                replaceDomain: (state, { domain }) => {
                    const domains: OrganizationDomainType[] = [...state.filter(({ id }) => id !== domain.id), domain]
                    domains.sort((a, b) => a.domain.localeCompare(b.domain))
                    return domains
                },
            },
        ],
        addModalShown: [
            false,
            {
                showAddDomainModal: () => true,
                hideAddDomainModal: () => false,
                addVerifiedDomainSuccess: () => false,
            },
        ],
        configureSAMLModalId: [
            null as null | string,
            {
                setConfigureSAMLModalId: (_, { id }) => id,
            },
        ],
        configureSCIMModalId: [
            null as null | string,
            {
                setConfigureSCIMModalId: (_, { id }) => id,
            },
        ],
        configureIdJagModalId: [
            null as null | string,
            {
                setConfigureIdJagModalId: (_, { id }) => id,
            },
        ],
        scimLogsModalId: [
            null as null | string,
            {
                setScimLogsModalId: (_, { id }) => id,
            },
        ],
        scimLogsStatusFilter: [
            'all' as 'all' | 'success' | '4xx' | '5xx',
            {
                setScimLogsStatusFilter: (_, { filter }) => filter,
                setScimLogsModalId: () => 'all',
            },
        ],
        scimLogsSearch: [
            '' as string,
            {
                setScimLogsSearch: (_, { search }) => search,
                setScimLogsModalId: () => '',
            },
        ],
        scimLogsPage: [
            1 as number,
            {
                setScimLogsPage: (_, { page }) => page,
                setScimLogsModalId: () => 1,
                setScimLogsStatusFilter: () => 1,
                setScimLogsSearch: () => 1,
            },
        ],
        verifyModal: [
            null as string | null,
            {
                setVerifyModal: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                loadVerifiedDomains: async () =>
                    (await api.get(`api/organizations/${values.currentOrganizationId}/domains`))
                        .results as OrganizationDomainType[],
                addVerifiedDomain: async (domain: string) => {
                    const response = await api.create<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganizationId}/domains`,
                        {
                            domain,
                        }
                    )
                    return [...values.verifiedDomains, response]
                },
                deleteVerifiedDomain: async (id: string) => {
                    await api.delete(`api/organizations/${values.currentOrganizationId}/domains/${id}`)
                    return values.verifiedDomains.filter((domain) => domain.id !== id)
                },
            },
        ],
        updatingDomain: [
            false,
            {
                updateDomain: async (payload: OrganizationDomainUpdatePayload) => {
                    const response = await api.update<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganizationId}/domains/${payload.id}`,
                        { ...payload, id: undefined }
                    )
                    lemonToast.success('Domain updated successfully! Changes will take effect immediately.')
                    actions.replaceDomain(response)
                    return false
                },
                verifyDomain: async () => {
                    const response = await api.create<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganizationId}/domains/${values.verifyModal}/verify`
                    )
                    if (response.is_verified) {
                        lemonToast.success('Domain verified successfully.')
                    } else {
                        lemonToast.warning(
                            'We could not verify your domain yet. DNS propagation may take up to 72 hours. Please try again later.'
                        )
                    }
                    actions.replaceDomain(response)
                    actions.setVerifyModal(null)
                    return false
                },
            },
        ],
        scimConfig: [
            {} as SCIMConfigType,
            {
                loadScimConfig: async (domainId: string) => {
                    const domain = values.verifiedDomains.find(({ id }) => id === domainId)
                    return {
                        id: domainId,
                        scim_enabled: domain?.scim_enabled ?? false,
                        scim_base_url: domain?.scim_base_url,
                    }
                },
                enableScim: async (domainId: string) => {
                    const orgId = values.currentOrganizationId as string
                    const domain = values.verifiedDomains.find(({ id }) => id === domainId)
                    if (!domain) {
                        return values.scimConfig
                    }
                    const configId = await ensureIdpConfigId(orgId, domain)
                    const config = await identityProviderConfigsPartialUpdate(orgId, configId, { scim_enabled: true })
                    // Refresh the domain so its SCIM base URL (per-domain, reverse-synced) is current.
                    const refreshed = await refreshDomain(orgId, domainId, actions.replaceDomain)
                    lemonToast.success('SCIM enabled successfully!')
                    return {
                        id: domainId,
                        scim_enabled: config.scim_enabled,
                        scim_base_url: refreshed.scim_base_url,
                        scim_bearer_token: config.scim_bearer_token ?? undefined,
                    }
                },
                disableScim: async (domainId: string) => {
                    const orgId = values.currentOrganizationId as string
                    const domain = values.verifiedDomains.find(({ id }) => id === domainId)
                    if (!domain) {
                        return values.scimConfig
                    }
                    const configId = await ensureIdpConfigId(orgId, domain)
                    const config = await identityProviderConfigsPartialUpdate(orgId, configId, { scim_enabled: false })
                    const refreshed = await refreshDomain(orgId, domainId, actions.replaceDomain)
                    lemonToast.success('SCIM disabled successfully!')
                    return {
                        id: domainId,
                        scim_enabled: config.scim_enabled,
                        scim_base_url: refreshed.scim_base_url,
                    }
                },
                regenerateScimToken: async (domainId: string) => {
                    const orgId = values.currentOrganizationId as string
                    const domain = values.verifiedDomains.find(({ id }) => id === domainId)
                    if (!domain?.identity_provider_config) {
                        return values.scimConfig
                    }
                    const response = await identityProviderConfigsScimTokenCreate(
                        orgId,
                        domain.identity_provider_config
                    )
                    lemonToast.success('SCIM token regenerated successfully!')
                    return {
                        id: domainId,
                        scim_enabled: response.scim_enabled,
                        scim_base_url: domain.scim_base_url,
                        scim_bearer_token: response.scim_bearer_token,
                    }
                },
            },
        ],
        scimLogs: [
            null as PaginatedSCIMRequestLogs | null,
            {
                setScimLogsModalId: () => null,
                loadScimLogs: async ({ domainId, page }: { domainId: string; page?: number }, breakpoint) => {
                    await breakpoint(300)
                    const params: Record<string, string> = {}
                    if (values.scimLogsStatusFilter === 'success') {
                        params.status_min = '200'
                        params.status_max = '299'
                    } else if (values.scimLogsStatusFilter === '4xx') {
                        params.status_min = '400'
                        params.status_max = '499'
                    } else if (values.scimLogsStatusFilter === '5xx') {
                        params.status_min = '500'
                    }
                    if (values.scimLogsSearch) {
                        params.search = values.scimLogsSearch
                    }
                    if (page) {
                        params.page = String(page)
                    }
                    const queryString = new URLSearchParams(params).toString()
                    const url = `api/organizations/${values.currentOrganizationId}/domains/${domainId}/scim/logs${queryString ? `?${queryString}` : ''}`
                    const response = await api.get(url)
                    await breakpoint()
                    return response
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setConfigureSAMLModalId: ({ id }) => {
            const domain = values.verifiedDomains.find(({ id: _idToFind }) => _idToFind === id)
            if (id && domain) {
                const { saml_acs_url, saml_entity_id, saml_x509_cert } = domain
                actions.setSamlConfigValues({ saml_acs_url, saml_entity_id, saml_x509_cert, id })
            }
        },
        setConfigureIdJagModalId: ({ id }) => {
            const domain = values.verifiedDomains.find(({ id: _idToFind }) => _idToFind === id)
            if (id && domain) {
                const { id_jag_issuer_url, id_jag_jwks_url, id_jag_allowed_clients } = domain
                actions.setIdJagConfigValues({
                    id,
                    id_jag_issuer_url: id_jag_issuer_url ?? '',
                    id_jag_jwks_url: id_jag_jwks_url ?? '',
                    id_jag_allowed_clients: id_jag_allowed_clients ?? [],
                })
            }
        },
        setConfigureSCIMModalId: ({ id }) => {
            if (id) {
                actions.loadScimConfig(id)
            }
        },
        setScimLogsModalId: ({ id }) => {
            if (id) {
                actions.loadScimLogs({ domainId: id })
            }
        },
        setScimLogsStatusFilter: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId })
            }
        },
        setScimLogsSearch: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId })
            }
        },
        setScimLogsPage: ({ page }) => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId, page })
            }
        },
        reloadScimLogs: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId, page: values.scimLogsPage })
            }
        },
    })),
    selectors({
        domainBeingVerified: [
            (s) => [s.verifiedDomains, s.verifyModal],
            (verifiedDomains, verifyingId): OrganizationDomainType | null =>
                (verifyingId && verifiedDomains.find(({ id }) => id === verifyingId)) || null,
        ],
        isSSOEnforcementAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SSO_ENFORCEMENT),
        ],
        isSAMLAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SAML),
        ],
        isSCIMAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SCIM),
        ],
        isXAAAuthenticationAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.XAA_AUTHENTICATION),
        ],
    }),
    afterMount(({ actions }) => actions.loadVerifiedDomains()),
    bindModalToUrl({
        urlKey: 'add-domain',
        openActionKey: 'showAddDomainModal',
        closeActionKey: 'hideAddDomainModal',
        isOpenKey: 'addModalShown',
    }),
    forms(({ actions, values }) => ({
        samlConfig: {
            defaults: {} as SAMLConfigType,
            errors: (payload) => ({
                saml_acs_url:
                    payload.saml_acs_url && !payload.saml_acs_url.match(SECURE_URL_REGEX)
                        ? 'Please enter a valid URL, including https://'
                        : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const { id, saml_acs_url, saml_entity_id, saml_x509_cert } = payload
                if (!id) {
                    return
                }
                const orgId = values.currentOrganizationId as string
                const domain = values.verifiedDomains.find(({ id: _id }) => _id === id)
                if (!domain) {
                    return
                }
                const configId = await ensureIdpConfigId(orgId, domain)
                await identityProviderConfigsPartialUpdate(orgId, configId, {
                    saml_acs_url,
                    saml_entity_id,
                    saml_x509_cert,
                })
                breakpoint()
                const refreshed = await refreshDomain(orgId, id, actions.replaceDomain)
                actions.setConfigureSAMLModalId(null)
                actions.setSamlConfigValues({})
                lemonToast.success(`SAML configuration for ${refreshed.domain} updated successfully.`)
            },
        },
        idJagConfig: {
            defaults: {} as IdJagConfigType,
            errors: (payload) => ({
                id_jag_issuer_url:
                    payload.id_jag_issuer_url && !payload.id_jag_issuer_url.match(SECURE_URL_REGEX)
                        ? 'Please enter a valid URL, including https://'
                        : undefined,
                id_jag_jwks_url:
                    payload.id_jag_jwks_url && !payload.id_jag_jwks_url.match(SECURE_URL_REGEX)
                        ? 'Please enter a valid URL, including https://'
                        : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const { id, id_jag_issuer_url, id_jag_jwks_url, id_jag_allowed_clients } = payload
                if (!id) {
                    return
                }
                const orgId = values.currentOrganizationId as string
                const domain = values.verifiedDomains.find(({ id: _id }) => _id === id)
                if (!domain) {
                    return
                }
                const configId = await ensureIdpConfigId(orgId, domain)
                await identityProviderConfigsPartialUpdate(orgId, configId, {
                    id_jag_issuer_url: id_jag_issuer_url?.trim() || null,
                    id_jag_jwks_url: id_jag_jwks_url?.trim() || null,
                    id_jag_allowed_clients: id_jag_allowed_clients ?? [],
                })
                breakpoint()
                const refreshed = await refreshDomain(orgId, id, actions.replaceDomain)
                actions.setConfigureIdJagModalId(null)
                actions.setIdJagConfigValues({})
                lemonToast.success(`XAA configuration for ${refreshed.domain} updated successfully.`)
            },
        },
    })),
])
